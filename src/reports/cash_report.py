"""Cash game HTML report generator.

Produces identical output to the original poker_cash_analyzer.py,
but reads data from the SQLite database via CashAnalyzer.
"""

from datetime import datetime

from src.analyzers.cash import CashAnalyzer
from src.analyzers.ev import EVAnalyzer


def generate_cash_report(analyzer: CashAnalyzer,
                         output_file: str = 'output/cash_report.html',
                         ev_analyzer: EVAnalyzer = None) -> str:
    """Generate the cash game HTML report."""
    summary = analyzer.get_summary()
    daily_reports = analyzer.get_daily_reports_with_sessions(ev_analyzer=ev_analyzer)
    preflop_stats = analyzer.get_preflop_stats()
    postflop_stats = analyzer.get_postflop_stats()
    positional_stats = analyzer.get_positional_stats()
    stack_depth_data = analyzer.get_stack_depth_stats()
    leak_analysis = analyzer.get_leak_analysis()
    redline_data = analyzer.get_redline_blueline()
    bet_sizing_data = analyzer.get_bet_sizing_analysis()
    tilt_data = analyzer.get_tilt_analysis()
    hand_matrix_data = analyzer.get_hand_matrix()
    ev_stats = ev_analyzer.get_ev_analysis() if ev_analyzer else None
    decision_ev_stats = ev_analyzer.get_decision_ev_analysis() if ev_analyzer else None

    total_hands = summary['total_hands']
    total_net = summary['total_net']
    total_days = summary['total_days']
    positive_days = summary['positive_days']
    negative_days = summary['negative_days']
    avg_per_day = summary['avg_per_day']

    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relat\u00f3rio Cash 2026</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        h1 {
            text-align: center;
            color: #00ff88;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 0 0 10px rgba(0, 255, 136, 0.5);
        }

        .summary {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 30px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        .summary h2 {
            color: #00ff88;
            margin-bottom: 15px;
        }

        .summary-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
        }

        .stat-card {
            background: rgba(0, 255, 136, 0.1);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }

        .stat-label {
            font-size: 0.9em;
            color: #a0a0a0;
            margin-bottom: 5px;
        }

        .stat-value {
            font-size: 1.8em;
            font-weight: bold;
        }

        .positive {
            color: #00ff88;
        }

        .negative {
            color: #ff4444;
        }

        .daily-report {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        .daily-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid rgba(0, 255, 136, 0.3);
        }

        .daily-header h3 {
            color: #00ff88;
            font-size: 1.5em;
        }

        .daily-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .daily-stat {
            background: rgba(0, 0, 0, 0.2);
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }

        .notable-hands {
            margin-top: 15px;
        }

        .notable-hands h4 {
            color: #00ff88;
            margin-bottom: 10px;
        }

        .hand-card {
            background: rgba(0, 0, 0, 0.3);
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 4px solid;
        }

        .hand-card.win {
            border-left-color: #00ff88;
        }

        .hand-card.loss {
            border-left-color: #ff4444;
        }

        .hand-details {
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
        }

        .hand-info {
            font-size: 0.9em;
        }

        .cards {
            font-weight: bold;
            color: #ffd700;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }

        th, td {
            padding: 12px;
            text-align: left;
        }

        th {
            background: rgba(0, 255, 136, 0.2);
            color: #00ff88;
            font-weight: bold;
        }

        tr:nth-child(even) {
            background: rgba(255, 255, 255, 0.02);
        }

        .footer {
            text-align: center;
            margin-top: 40px;
            color: #a0a0a0;
            font-size: 0.9em;
        }

        .player-stats {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 30px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        .player-stats h2 {
            color: #00ff88;
            margin-bottom: 15px;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }

        .stat-card .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.7em;
            font-weight: bold;
            text-transform: uppercase;
            margin-top: 5px;
        }

        .badge-good {
            background: rgba(0, 255, 136, 0.2);
            color: #00ff88;
        }

        .badge-warning {
            background: rgba(255, 193, 7, 0.2);
            color: #ffc107;
        }

        .badge-danger {
            background: rgba(255, 68, 68, 0.2);
            color: #ff4444;
        }

        .stat-detail {
            font-size: 0.75em;
            color: #888;
            margin-top: 3px;
        }

        .position-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }

        .position-table th, .position-table td {
            padding: 10px 12px;
            text-align: center;
        }

        .section-subtitle {
            color: #a0a0a0;
            font-size: 1em;
            margin: 20px 0 10px 0;
        }

        /* ── Session Accordion ──────────────────────────────── */
        .session-accordion {
            margin-top: 15px;
        }

        .session-card {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 10px;
            margin-bottom: 10px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            overflow: hidden;
        }

        .session-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            cursor: pointer;
            user-select: none;
            transition: background 0.2s;
        }

        .session-header:hover {
            background: rgba(255, 255, 255, 0.03);
        }

        .session-header-left {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .session-header-left .session-num {
            color: #00ff88;
            font-weight: bold;
            font-size: 0.9em;
        }

        .session-header-left .session-time {
            color: #a0a0a0;
            font-size: 0.85em;
        }

        .session-header-right {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .session-header-right .session-hands {
            color: #a0a0a0;
            font-size: 0.85em;
        }

        .session-header-right .session-profit {
            font-weight: bold;
            font-size: 1.1em;
        }

        .session-toggle {
            color: #a0a0a0;
            font-size: 0.8em;
            transition: transform 0.3s;
        }

        .session-card.open .session-toggle {
            transform: rotate(180deg);
        }

        .session-body {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease-out;
        }

        .session-card.open .session-body {
            max-height: 2000px;
            transition: max-height 0.5s ease-in;
        }

        .session-content {
            padding: 0 16px 16px 16px;
        }

        .session-info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 10px;
            margin-bottom: 15px;
        }

        .session-info-item {
            background: rgba(0, 0, 0, 0.2);
            padding: 8px;
            border-radius: 6px;
            text-align: center;
        }

        .session-info-item .stat-label {
            font-size: 0.75em;
        }

        .session-info-item .stat-value {
            font-size: 1.2em;
        }

        .session-stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
            gap: 8px;
            margin-bottom: 15px;
        }

        .session-stat-card {
            background: rgba(0, 255, 136, 0.05);
            padding: 8px;
            border-radius: 6px;
            text-align: center;
        }

        .session-stat-card .stat-label {
            font-size: 0.7em;
        }

        .session-stat-card .stat-value {
            font-size: 1em;
        }

        .session-stat-card .badge {
            font-size: 0.6em;
            padding: 1px 5px;
        }

        /* ── Day Summary Stats ──────────────────────────────── */
        .day-summary-stats {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }

        .day-summary-stats h4 {
            color: #a0a0a0;
            font-size: 0.9em;
            margin-bottom: 10px;
        }

        .day-stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
            gap: 8px;
        }

        /* ── Session Comparison ──────────────────────────────── */
        .session-comparison {
            margin-top: 15px;
        }

        .session-comparison table {
            margin-top: 5px;
        }

        /* ── EV Leak Cards ──────────────────────────────── */
        .leaks-container {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin: 15px 0;
        }

        .leak-card {
            background: rgba(255, 68, 68, 0.08);
            border: 1px solid rgba(255, 68, 68, 0.25);
            border-radius: 10px;
            padding: 15px;
        }

        .leak-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }

        .leak-rank {
            background: rgba(255, 68, 68, 0.4);
            color: #fff;
            border-radius: 50%;
            width: 26px;
            height: 26px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 0.8em;
            flex-shrink: 0;
        }

        .leak-description {
            font-weight: bold;
            color: #ff9999;
            font-size: 0.95em;
        }

        .leak-stats {
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            font-size: 0.85em;
            color: #a0a0a0;
            margin-bottom: 8px;
        }

        .leak-suggestion {
            font-size: 0.85em;
            color: #b0e0b0;
            padding: 8px 10px;
            background: rgba(0, 255, 136, 0.05);
            border-radius: 6px;
            border-left: 3px solid rgba(0, 255, 136, 0.5);
        }

        /* ── VPIP Drill-Down Modal ──────────────────────────────── */
        .vpip-modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.75);
            z-index: 1000;
            backdrop-filter: blur(4px);
            animation: fadeIn 0.2s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to   { opacity: 1; }
        }

        .vpip-modal {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border: 1px solid rgba(0, 255, 136, 0.3);
            border-radius: 15px;
            padding: 30px;
            max-width: 860px;
            width: 92%;
            max-height: 82vh;
            overflow-y: auto;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
            animation: slideUp 0.25s ease;
        }

        @keyframes slideUp {
            from { transform: translate(-50%, -45%); opacity: 0; }
            to   { transform: translate(-50%, -50%); opacity: 1; }
        }

        .vpip-modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid rgba(0, 255, 136, 0.2);
        }

        .vpip-modal-title {
            color: #00ff88;
            font-size: 1.4em;
            font-weight: bold;
            text-shadow: 0 0 8px rgba(0, 255, 136, 0.4);
        }

        .vpip-modal-close {
            background: none;
            border: none;
            color: #a0a0a0;
            font-size: 1.4em;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: 6px;
            transition: color 0.2s, background 0.2s;
        }

        .vpip-modal-close:hover {
            color: #ff4444;
            background: rgba(255, 68, 68, 0.1);
        }

        .vpip-tab-bar {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }

        .vpip-tab-btn {
            padding: 8px 18px;
            border-radius: 8px;
            border: 1px solid rgba(0, 255, 136, 0.3);
            background: rgba(255, 255, 255, 0.05);
            color: #a0a0a0;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.2s;
        }

        .vpip-tab-btn:hover {
            background: rgba(0, 255, 136, 0.1);
            color: #e0e0e0;
        }

        .vpip-tab-btn.active {
            background: rgba(0, 255, 136, 0.2);
            color: #00ff88;
            border-color: rgba(0, 255, 136, 0.6);
        }

        .vpip-panel {
            display: none;
        }

        .vpip-panel.active {
            display: block;
        }

        .stat-card.vpip-clickable {
            cursor: pointer;
            transition: transform 0.15s, box-shadow 0.15s, background 0.15s;
        }

        .stat-card.vpip-clickable:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0, 255, 136, 0.25);
            background: rgba(0, 255, 136, 0.18);
        }

        .vpip-hint {
            font-size: 0.65em;
            color: rgba(0, 255, 136, 0.6);
            margin-top: 4px;
        }

        /* ── Responsive ──────────────────────────────── */
        @media (max-width: 768px) {
            .summary-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .session-info-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .session-stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .daily-header {
                flex-direction: column;
                gap: 10px;
                align-items: flex-start;
            }
            .hand-details {
                flex-direction: column;
            }
        }

        @media (max-width: 480px) {
            body {
                padding: 10px;
            }
            .summary-grid {
                grid-template-columns: 1fr;
            }
            h1 {
                font-size: 1.8em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Relat\u00f3rio Cash 2026</h1>
"""

    net_class = 'positive' if total_net >= 0 else 'negative'
    avg_class = 'positive' if avg_per_day >= 0 else 'negative'

    html += f"""
        <div class="summary">
            <h2>Resumo Geral</h2>
            <div class="summary-grid">
                <div class="stat-card">
                    <div class="stat-label">Total de M\u00e3os</div>
                    <div class="stat-value">{total_hands}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Dias Jogados</div>
                    <div class="stat-value">{total_days}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Dias Positivos</div>
                    <div class="stat-value positive">{positive_days}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Dias Negativos</div>
                    <div class="stat-value negative">{negative_days}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado Total</div>
                    <div class="stat-value {net_class}">${total_net:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">M\u00e9dia por Dia</div>
                    <div class="stat-value {avg_class}">${avg_per_day:.2f}</div>
                </div>
            </div>
        </div>
"""

    # ── Player Stats Section ──────────────────────────────────────
    overall = preflop_stats.get('overall', {})
    by_position = preflop_stats.get('by_position', {})

    if overall.get('total_hands', 0) > 0:
        html += _render_player_stats(overall, by_position, positional_stats, stack_depth_data)

    # ── Postflop Analysis Section ──────────────────────────────────
    postflop_overall = postflop_stats.get('overall', {})
    if postflop_overall.get('saw_flop_hands', 0) > 0:
        html += _render_postflop_stats(
            postflop_overall,
            postflop_stats.get('by_street', {}),
            postflop_stats.get('by_week', {}),
        )

    # ── Positional Analysis Section ──────────────────────────────────
    if positional_stats.get('by_position'):
        html += _render_positional_analysis(positional_stats)

    # ── Stack Depth Analysis Section ──────────────────────────────────
    if stack_depth_data.get('by_tier'):
        html += _render_stack_depth_analysis(stack_depth_data)

    # ── Leak Finder Section ───────────────────────────────────────────
    if leak_analysis and leak_analysis.get('total_leaks', 0) > 0:
        html += _render_leak_finder(leak_analysis)

    # ── Red Line / Blue Line Section ──────────────────────────────────
    if redline_data and redline_data.get('total_hands', 0) >= 2:
        html += _render_redline_blueline(redline_data)

    # ── Bet Sizing & Pot-Type Segmentation Section ─────────────────────
    if bet_sizing_data and bet_sizing_data.get('total_hands', 0) >= 5:
        html += _render_bet_sizing_analysis(bet_sizing_data)

    # ── Tilt Detection & Time/Duration Performance Section ─────────────
    if tilt_data:
        html += _render_tilt_analysis(tilt_data)

    # ── Preflop Range Visualization Section ─────────────────────────
    if hand_matrix_data and hand_matrix_data.get('total_hands', 0) >= 5:
        html += _render_range_analysis(hand_matrix_data)

    # ── Decision-Tree EV Analysis Section ───────────────────────────
    _total_decisions = 0
    if decision_ev_stats:
        _total_decisions = sum(
            decision_ev_stats['by_street'][st][dec]['count']
            for st in ('preflop', 'flop', 'turn', 'river')
            for dec in ('fold', 'call', 'raise')
        )

    if decision_ev_stats and _total_decisions > 0:
        html += _render_decision_ev_analysis(decision_ev_stats, ev_stats)
    elif ev_stats and ev_stats.get('overall', {}).get('allin_hands', 0) > 0:
        # Fallback: show standalone all-in EV section when no action data
        html += _render_ev_analysis(
            ev_stats['overall'],
            ev_stats.get('by_stakes', {}),
            ev_stats.get('chart_data', []),
        )

    # ── Daily Reports with Session Breakdown ────────────────────────
    for report in daily_reports:
        html += _render_daily_report(report)

    # ── VPIP Drill-Down Modal (US-018) ───────────────────────────────────
    html += _render_vpip_modal(positional_stats, stack_depth_data)

    html += """
        <div class="footer">
            <p>Relat\u00f3rio gerado automaticamente</p>
        </div>
    </div>
    <script>
    document.querySelectorAll('.session-header').forEach(function(header) {
        header.addEventListener('click', function() {
            this.parentElement.classList.toggle('open');
        });
    });

    /* ── VPIP Drill-Down Modal (US-018) ── */
    function openVpipModal() {
        var overlay = document.getElementById('vpip-modal-overlay');
        if (overlay) {
            overlay.style.display = 'block';
            document.body.style.overflow = 'hidden';
        }
    }

    function closeVpipModal() {
        var overlay = document.getElementById('vpip-modal-overlay');
        if (overlay) {
            overlay.style.display = 'none';
            document.body.style.overflow = '';
        }
    }

    function closeVpipModalOverlay(event) {
        if (event.target === document.getElementById('vpip-modal-overlay')) {
            closeVpipModal();
        }
    }

    function switchVpipTab(tab) {
        document.querySelectorAll('.vpip-panel').forEach(function(p) {
            p.classList.remove('active');
        });
        document.querySelectorAll('.vpip-tab-btn').forEach(function(b) {
            b.classList.remove('active');
        });
        var panel = document.getElementById('vpip-panel-' + tab);
        if (panel) { panel.classList.add('active'); }
        var btn = document.getElementById('vpip-tab-btn-' + tab);
        if (btn) { btn.classList.add('active'); }
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') { closeVpipModal(); }
    });
    </script>
</body>
</html>
"""

    from pathlib import Path
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Report generated: {output_file}")
    return output_file


def _render_daily_report(report: dict) -> str:
    """Render a single day's report with session breakdown."""
    date_obj = datetime.strptime(report['date'], '%Y-%m-%d')
    date_formatted = date_obj.strftime('%d/%m/%Y (%A)')
    net = report['net']
    net_class = 'positive' if net >= 0 else 'negative'
    num_sessions = report['num_sessions']
    total_invested = report['total_invested']

    html = f"""
        <div class="daily-report">
            <div class="daily-header">
                <h3>{date_formatted}</h3>
                <span class="stat-value {net_class}">${net:.2f}</span>
            </div>

            <div class="daily-stats">
                <div class="daily-stat">
                    <div class="stat-label">Sess\u00f5es</div>
                    <div class="stat-value">{num_sessions}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">M\u00e3os Jogadas</div>
                    <div class="stat-value">{report['hands_count']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value">${total_invested:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Resultado Final</div>
                    <div class="stat-value {net_class}">${net:.2f}</div>
                </div>
            </div>
"""

    # Session accordion
    sessions = report.get('sessions', [])
    if sessions:
        html += '            <div class="session-accordion">\n'
        for i, sd in enumerate(sessions):
            html += _render_session_card(sd, i + 1)
        html += '            </div>\n'

    # Day summary stats (weighted average from sessions)
    day_stats = report.get('day_stats', {})
    if day_stats and day_stats.get('total_hands', 0) > 0:
        html += _render_day_summary_stats(day_stats)

    # Session comparison
    comparison = report.get('comparison', {})
    if comparison and len(sessions) >= 2:
        html += _render_session_comparison(comparison, sessions)

    html += """
        </div>
"""
    return html


def _render_session_card(sd: dict, session_num: int) -> str:
    """Render a single session accordion card."""
    profit = sd.get('profit', 0)
    profit_class = 'positive' if profit >= 0 else 'negative'
    hands_count = sd.get('hands_count', 0)
    duration = sd.get('duration_minutes', 0)

    # Parse time display
    start_time = sd.get('start_time', '')
    end_time = sd.get('end_time', '')
    try:
        start_display = datetime.fromisoformat(start_time).strftime('%H:%M')
        end_display = datetime.fromisoformat(end_time).strftime('%H:%M')
        time_display = f'{start_display} - {end_display}'
    except (ValueError, TypeError):
        time_display = 'N/A'

    # Duration display
    if duration > 0:
        hours = duration // 60
        mins = duration % 60
        dur_display = f'{hours}h{mins:02d}' if hours > 0 else f'{mins}min'
    else:
        dur_display = 'N/A'

    html = f"""
                <div class="session-card">
                    <div class="session-header">
                        <div class="session-header-left">
                            <span class="session-num">Sess\u00e3o {session_num}</span>
                            <span class="session-time">{time_display}</span>
                        </div>
                        <div class="session-header-right">
                            <span class="session-hands">{hands_count} m\u00e3os</span>
                            <span class="session-profit {profit_class}">${profit:.2f}</span>
                            <span class="session-toggle">\u25bc</span>
                        </div>
                    </div>
                    <div class="session-body">
                        <div class="session-content">
                            <div class="session-info-grid">
                                <div class="session-info-item">
                                    <div class="stat-label">Dura\u00e7\u00e3o</div>
                                    <div class="stat-value">{dur_display}</div>
                                </div>
                                <div class="session-info-item">
                                    <div class="stat-label">Buy-in</div>
                                    <div class="stat-value">${sd.get('buy_in', 0):.2f}</div>
                                </div>
                                <div class="session-info-item">
                                    <div class="stat-label">Cash-out</div>
                                    <div class="stat-value">${sd.get('cash_out', 0):.2f}</div>
                                </div>
                                <div class="session-info-item">
                                    <div class="stat-label">Profit</div>
                                    <div class="stat-value {profit_class}">${profit:.2f}</div>
                                </div>
                                <div class="session-info-item">
                                    <div class="stat-label">M\u00e3os</div>
                                    <div class="stat-value">{hands_count}</div>
                                </div>
                                <div class="session-info-item">
                                    <div class="stat-label">Min Stack</div>
                                    <div class="stat-value">${sd.get('min_stack', 0):.2f}</div>
                                </div>
                            </div>
"""

    # Session stats with badges
    stats = sd.get('stats', {})
    if stats and stats.get('total_hands', 0) > 0:
        html += _render_session_stats(stats)

    # Sparkline
    sparkline = sd.get('sparkline', [])
    if sparkline and len(sparkline) >= 2:
        html += _render_sparkline(sparkline)

    # Session EV analysis
    ev_data = sd.get('ev_data')
    if ev_data:
        html += _render_session_ev_summary(ev_data)

    # Notable hands within session
    bw = sd.get('biggest_win')
    bl = sd.get('biggest_loss')
    if bw or bl:
        html += '                            <div class="notable-hands">\n'
        html += '                                <h4>M\u00e3os Not\u00e1veis</h4>\n'
        if bw:
            html += _render_hand_card(bw, is_win=True)
        if bl:
            html += _render_hand_card(bl, is_win=False)
        html += '                            </div>\n'

    html += """
                        </div>
                    </div>
                </div>
"""
    return html


def _render_session_stats(stats: dict) -> str:
    """Render session-level stats with health badges."""

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    def mini_stat(label: str, value: float, health: str, fmt: str = '{:.1f}%') -> str:
        return (
            f'<div class="session-stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{fmt.format(value)}</div>'
            f'{badge_html(health)}'
            f'</div>'
        )

    html = '                            <div class="session-stats-grid">\n'
    html += f'                                {mini_stat("VPIP", stats["vpip"], stats["vpip_health"])}\n'
    html += f'                                {mini_stat("PFR", stats["pfr"], stats["pfr_health"])}\n'
    html += f'                                {mini_stat("3-Bet", stats["three_bet"], stats["three_bet_health"])}\n'
    html += f'                                {mini_stat("AF", stats["af"], stats["af_health"], "{:.2f}")}\n'
    html += f'                                {mini_stat("WTSD%", stats["wtsd"], stats["wtsd_health"])}\n'
    html += f'                                {mini_stat("W$SD%", stats["wsd"], stats["wsd_health"])}\n'
    html += f'                                {mini_stat("CBet%", stats["cbet"], stats["cbet_health"])}\n'
    html += '                            </div>\n'
    return html


def _render_sparkline(data: list[dict]) -> str:
    """Render inline SVG sparkline for session profit evolution."""
    width = 300
    height = 60
    margin = 5
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    values = [d['profit'] for d in data]
    y_min = min(values)
    y_max = max(values)
    y_range = y_max - y_min if y_max != y_min else 1.0
    x_max = len(values) - 1
    if x_max == 0:
        x_max = 1

    def sx(i):
        return margin + (i / x_max) * plot_w

    def sy(v):
        return margin + plot_h - ((v - y_min) / y_range) * plot_h

    points = ' '.join(f'{sx(i):.1f},{sy(v):.1f}' for i, v in enumerate(values))

    final_val = values[-1]
    line_color = '#00ff88' if final_val >= 0 else '#ff4444'

    # Zero line
    zero_line = ''
    if y_min < 0 < y_max:
        zy = sy(0)
        zero_line = (
            f'<line x1="{margin}" y1="{zy:.1f}" '
            f'x2="{width - margin}" y2="{zy:.1f}" '
            f'stroke="rgba(255,255,255,0.2)" stroke-width="0.5" '
            f'stroke-dasharray="2,2"/>'
        )

    svg = f"""                            <div style="margin:10px 0;">
                                <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                                     style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.15);border-radius:6px;">
                                    {zero_line}
                                    <polyline points="{points}"
                                              fill="none" stroke="{line_color}" stroke-width="1.5"
                                              stroke-linejoin="round"/>
                                </svg>
                            </div>
"""
    return svg


def _render_session_ev_summary(ev_data: dict) -> str:
    """Render session-level EV analysis summary with Lucky/Unlucky badge and mini chart."""
    if not ev_data or ev_data.get('total_hands', 0) == 0:
        return ''
    if ev_data.get('allin_hands', 0) == 0:
        return ''

    luck = ev_data.get('luck_factor', 0)
    luck_class = 'positive' if luck >= 0 else 'negative'
    luck_label = 'acima do EV' if luck >= 0 else 'abaixo do EV'

    # Lucky/Unlucky badge
    if luck >= 0:
        badge = '<span class="badge badge-good" style="font-size:0.85em;">Lucky</span>'
    else:
        badge = '<span class="badge badge-danger" style="font-size:0.85em;">Unlucky</span>'

    html = f"""                            <div class="session-ev-summary" style="margin:10px 0;padding:10px;background:rgba(0,170,255,0.05);border:1px solid rgba(0,170,255,0.2);border-radius:8px;">
                                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                                    <h5 style="color:#00aaff;margin:0;font-size:0.95em;">EV da Sess\u00e3o</h5>
                                    {badge}
                                </div>
                                <div class="session-stats-grid">
                                    <div class="session-stat-card">
                                        <div class="stat-label">All-in Hands</div>
                                        <div class="stat-value">{ev_data['allin_hands']}</div>
                                        <div class="stat-detail">{ev_data['total_hands']} total</div>
                                    </div>
                                    <div class="session-stat-card">
                                        <div class="stat-label">Real Net</div>
                                        <div class="stat-value {'positive' if ev_data['real_net'] >= 0 else 'negative'}">${ev_data['real_net']:.2f}</div>
                                    </div>
                                    <div class="session-stat-card">
                                        <div class="stat-label">EV Net</div>
                                        <div class="stat-value {'positive' if ev_data['ev_net'] >= 0 else 'negative'}">${ev_data['ev_net']:.2f}</div>
                                    </div>
                                    <div class="session-stat-card">
                                        <div class="stat-label">Luck Factor</div>
                                        <div class="stat-value {luck_class}">${luck:+.2f}</div>
                                        <div class="stat-detail">{luck_label}</div>
                                    </div>
                                </div>
"""

    # Mini EV chart
    chart_data = ev_data.get('chart_data', [])
    if chart_data and len(chart_data) >= 2:
        html += _render_mini_ev_chart(chart_data)

    html += """                            </div>
"""
    return html


def _render_mini_ev_chart(chart_data: list) -> str:
    """Render compact inline SVG chart for session EV vs Real (300x60)."""
    width = 300
    height = 60
    margin = 5
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    real_values = [d['real'] for d in chart_data]
    ev_values = [d['ev'] for d in chart_data]
    all_values = real_values + ev_values
    y_min = min(all_values)
    y_max = max(all_values)
    y_range = y_max - y_min if y_max != y_min else 1.0
    x_max = len(chart_data) - 1
    if x_max == 0:
        x_max = 1

    def sx(i):
        return margin + (i / x_max) * plot_w

    def sy(v):
        return margin + plot_h - ((v - y_min) / y_range) * plot_h

    real_points = ' '.join(f'{sx(i):.1f},{sy(v):.1f}' for i, v in enumerate(real_values))
    ev_points = ' '.join(f'{sx(i):.1f},{sy(v):.1f}' for i, v in enumerate(ev_values))

    # Zero line
    zero_line = ''
    if y_min < 0 < y_max:
        zy = sy(0)
        zero_line = (
            f'<line x1="{margin}" y1="{zy:.1f}" '
            f'x2="{width - margin}" y2="{zy:.1f}" '
            f'stroke="rgba(255,255,255,0.2)" stroke-width="0.5" '
            f'stroke-dasharray="2,2"/>'
        )

    svg = f"""                                <div style="margin:6px 0;">
                                    <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                                         style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.15);border-radius:6px;">
                                        {zero_line}
                                        <polyline points="{real_points}"
                                                  fill="none" stroke="#00ff88" stroke-width="1.5"
                                                  stroke-linejoin="round"/>
                                        <polyline points="{ev_points}"
                                                  fill="none" stroke="#ffa500" stroke-width="1.5"
                                                  stroke-linejoin="round" stroke-dasharray="4,2"/>
                                        <text x="{width - margin - 2}" y="{margin + 8}"
                                              text-anchor="end" fill="#00ff88" font-size="7">Real</text>
                                        <text x="{width - margin - 2}" y="{margin + 16}"
                                              text-anchor="end" fill="#ffa500" font-size="7">EV</text>
                                    </svg>
                                </div>
"""
    return svg


def _render_hand_card(hand: dict, is_win: bool) -> str:
    """Render a notable hand card (biggest win or loss)."""
    cards = hand.get('hero_cards') or 'N/A'
    invested = hand.get('invested', 0) or 0
    won = hand.get('won', 0) or 0
    net = hand.get('net', 0) or 0
    blinds = (f"${hand.get('blinds_sb', 0):.2f}/${hand.get('blinds_bb', 0):.2f}"
              if hand.get('blinds_sb') else 'N/A')

    css_class = 'win' if is_win else 'loss'
    result_class = 'positive' if is_win else 'negative'
    result_label = 'Lucro' if is_win else 'Perda'

    return f"""                                <div class="hand-card {css_class}">
                                    <div class="hand-details">
                                        <div class="hand-info">
                                            <span class="cards">Cards: {cards}</span> |
                                            Blinds: {blinds}
                                        </div>
                                        <div class="hand-info">
                                            Investido: ${invested:.2f} |
                                            Ganho: ${won:.2f} |
                                            <strong class="{result_class}">{result_label}: ${net:.2f}</strong>
                                        </div>
                                    </div>
                                </div>
"""


def _render_day_summary_stats(day_stats: dict) -> str:
    """Render day-level aggregated stats (weighted average from sessions)."""
    html = """
            <div class="day-summary-stats">
                <h4>Resumo do Dia (m\u00e9dia ponderada)</h4>
                <div class="day-stats-grid">
"""
    stats_items = [
        ('VPIP', day_stats.get('vpip', 0), '{:.1f}%'),
        ('PFR', day_stats.get('pfr', 0), '{:.1f}%'),
        ('3-Bet', day_stats.get('three_bet', 0), '{:.1f}%'),
        ('AF', day_stats.get('af', 0), '{:.2f}'),
        ('WTSD%', day_stats.get('wtsd', 0), '{:.1f}%'),
        ('W$SD%', day_stats.get('wsd', 0), '{:.1f}%'),
        ('CBet%', day_stats.get('cbet', 0), '{:.1f}%'),
    ]
    for label, value, fmt in stats_items:
        html += f"""                    <div class="daily-stat">
                        <div class="stat-label">{label}</div>
                        <div class="stat-value">{fmt.format(value)}</div>
                    </div>
"""
    html += """                </div>
            </div>
"""
    return html


def _render_session_comparison(comparison: dict, sessions: list[dict]) -> str:
    """Render visual comparison table between sessions of the day."""
    html = """
            <div class="session-comparison">
                <h4 class="section-subtitle">Comparativo entre Sess\u00f5es</h4>
                <table class="position-table">
                    <thead>
                        <tr>
                            <th>Stat</th>
"""
    for i, sd in enumerate(sessions):
        html += f'                            <th>S{i + 1}</th>\n'
    html += """                        </tr>
                    </thead>
                    <tbody>
"""

    stat_labels = {
        'vpip': ('VPIP', '{:.1f}%'),
        'pfr': ('PFR', '{:.1f}%'),
        'af': ('AF', '{:.2f}'),
        'wtsd': ('WTSD%', '{:.1f}%'),
        'wsd': ('W$SD%', '{:.1f}%'),
        'cbet': ('CBet%', '{:.1f}%'),
        'profit': ('Profit', '${:.2f}'),
    }

    for key, (label, fmt) in stat_labels.items():
        comp = comparison.get(key, {})
        best_idx = comp.get('best', -1)
        worst_idx = comp.get('worst', -1)
        html += f'                        <tr><td><strong>{label}</strong></td>\n'
        for i, sd in enumerate(sessions):
            if key == 'profit':
                val = sd.get('profit', 0)
            else:
                val = sd.get('stats', {}).get(key, 0)
            val_str = fmt.format(val)

            cell_style = ''
            if i == best_idx:
                cell_style = ' class="positive"'
            elif i == worst_idx:
                cell_style = ' class="negative"'
            html += f'                            <td{cell_style}>{val_str}</td>\n'
        html += '                        </tr>\n'

    html += """                    </tbody>
                </table>
            </div>
"""
    return html


def _render_player_stats(overall: dict, by_position: dict,
                         positional_stats: dict = None,
                         stack_depth_data: dict = None) -> str:
    """Render the Player Stats HTML section.

    When positional_stats or stack_depth_data are provided the VPIP card
    becomes clickable and opens the VPIP Drill-Down Modal (US-018).
    """
    has_modal = bool(
        (positional_stats and positional_stats.get('by_position'))
        or (stack_depth_data and stack_depth_data.get('by_tier'))
    )

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    def stat_card(label: str, value: float, health: str, detail: str = '') -> str:
        detail_html = f'<div class="stat-detail">{detail}</div>' if detail else ''
        return (
            f'<div class="stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{value:.1f}%</div>'
            f'{badge_html(health)}'
            f'{detail_html}'
            f'</div>'
        )

    def vpip_stat_card(value: float, health: str, detail: str = '') -> str:
        """VPIP card – clickable when modal data is available."""
        detail_html = f'<div class="stat-detail">{detail}</div>' if detail else ''
        if has_modal:
            hint = '<div class="vpip-hint">&#128269; clique para detalhes</div>'
            return (
                f'<div class="stat-card vpip-clickable" onclick="openVpipModal()" '
                f'title="Clique para ver breakdown por posi\u00e7\u00e3o e stack depth">'
                f'<div class="stat-label">VPIP</div>'
                f'<div class="stat-value">{value:.1f}%</div>'
                f'{badge_html(health)}'
                f'{detail_html}'
                f'{hint}'
                f'</div>'
            )
        return stat_card('VPIP', value, health, detail)

    vpip_detail = f'{overall["vpip_hands"]}/{overall["total_hands"]} m\u00e3os'
    pfr_detail = f'{overall["pfr_hands"]}/{overall["total_hands"]} m\u00e3os'
    three_bet_detail = f'{overall["three_bet_hands"]}/{overall["three_bet_opps"]} opps'
    fold_3bet_detail = f'{overall["fold_to_3bet_hands"]}/{overall["fold_to_3bet_opps"]} opps'
    ats_detail = f'{overall["ats_hands"]}/{overall["ats_opps"]} opps'

    html = f"""
        <div class="player-stats">
            <h2>Player Stats (Preflop)</h2>
            <div class="stats-grid">
                {vpip_stat_card(overall['vpip'], overall['vpip_health'], vpip_detail)}
                {stat_card('PFR', overall['pfr'], overall['pfr_health'], pfr_detail)}
                {stat_card('3-Bet', overall['three_bet'], overall['three_bet_health'], three_bet_detail)}
                {stat_card('Fold to 3-Bet', overall['fold_to_3bet'], overall['fold_to_3bet_health'], fold_3bet_detail)}
                {stat_card('ATS (Steal)', overall['ats'], overall['ats_health'], ats_detail)}
            </div>
"""

    # Position breakdown table
    position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
    positions_present = [p for p in position_order if p in by_position]

    if positions_present:
        html += """
            <h3 class="section-subtitle">Stats por Posi\u00e7\u00e3o</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Posi\u00e7\u00e3o</th>
                        <th>M\u00e3os</th>
                        <th>VPIP</th>
                        <th>PFR</th>
                        <th>3-Bet</th>
                        <th>ATS</th>
                    </tr>
                </thead>
                <tbody>
"""
        for pos in positions_present:
            ps = by_position[pos]
            ats_val = f'{ps["ats"]:.1f}%' if pos in ('CO', 'BTN', 'SB') else '-'
            html += f"""
                    <tr>
                        <td><strong>{pos}</strong></td>
                        <td>{ps['total_hands']}</td>
                        <td>{ps['vpip']:.1f}%</td>
                        <td>{ps['pfr']:.1f}%</td>
                        <td>{ps['three_bet']:.1f}%</td>
                        <td>{ats_val}</td>
                    </tr>
"""
        html += """
                </tbody>
            </table>
"""

    html += """
        </div>
"""
    return html


def _render_postflop_stats(overall: dict, by_street: dict, by_week: dict) -> str:
    """Render the Postflop Analysis HTML section."""

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    def stat_card(label: str, value: float, health: str, detail: str = '',
                  fmt: str = '{:.1f}%') -> str:
        val_str = fmt.format(value)
        detail_html = f'<div class="stat-detail">{detail}</div>' if detail else ''
        return (
            f'<div class="stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{val_str}</div>'
            f'{badge_html(health)}'
            f'{detail_html}'
            f'</div>'
        )

    af_detail = f'{overall["af_bets_raises"]} agg / {overall["af_calls"]} calls'
    wtsd_detail = f'{overall["wtsd_hands"]}/{overall["wtsd_opps"]} flops'
    wsd_detail = f'{overall["wsd_hands"]}/{overall["wsd_opps"]} showdowns'
    cbet_detail = f'{overall["cbet_hands"]}/{overall["cbet_opps"]} opps'
    fold_cbet_detail = f'{overall["fold_to_cbet_hands"]}/{overall["fold_to_cbet_opps"]} opps'
    cr_detail = f'{overall["check_raise_hands"]}/{overall["check_raise_opps"]} opps'

    html = f"""
        <div class="player-stats">
            <h2>Postflop Analysis</h2>
            <div class="stats-grid">
                {stat_card('AF', overall['af'], overall['af_health'], af_detail, '{:.2f}')}
                {stat_card('AFq', overall['afq'], 'good', '', '{:.1f}%')}
                {stat_card('WTSD%', overall['wtsd'], overall['wtsd_health'], wtsd_detail)}
                {stat_card('W$SD%', overall['wsd'], overall['wsd_health'], wsd_detail)}
                {stat_card('CBet%', overall['cbet'], overall['cbet_health'], cbet_detail)}
                {stat_card('Fold to CBet', overall['fold_to_cbet'], overall['fold_to_cbet_health'], fold_cbet_detail)}
                {stat_card('Check-Raise%', overall['check_raise'], overall['check_raise_health'], cr_detail)}
            </div>
"""

    # By street table
    html += """
            <h3 class="section-subtitle">Stats por Street</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Street</th>
                        <th>AF</th>
                        <th>AFq</th>
                        <th>Check-Raise%</th>
                    </tr>
                </thead>
                <tbody>
"""
    for street in ('flop', 'turn', 'river'):
        if street in by_street:
            s = by_street[street]
            html += f"""
                    <tr>
                        <td><strong>{street.capitalize()}</strong></td>
                        <td>{s['af']:.2f}</td>
                        <td>{s['afq']:.1f}%</td>
                        <td>{s['check_raise']:.1f}%</td>
                    </tr>
"""
    html += """
                </tbody>
            </table>
"""

    # Weekly trends table
    if by_week:
        html += """
            <h3 class="section-subtitle">Tend\u00eancias Semanais</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Semana</th>
                        <th>M\u00e3os</th>
                        <th>Saw Flop</th>
                        <th>AF</th>
                        <th>WTSD%</th>
                        <th>W$SD%</th>
                        <th>CBet%</th>
                    </tr>
                </thead>
                <tbody>
"""
        for week, ws in by_week.items():
            html += f"""
                    <tr>
                        <td><strong>{week}</strong></td>
                        <td>{ws['total_hands']}</td>
                        <td>{ws['saw_flop']}</td>
                        <td>{ws['af']:.2f}</td>
                        <td>{ws['wtsd']:.1f}%</td>
                        <td>{ws['wsd']:.1f}%</td>
                        <td>{ws['cbet']:.1f}%</td>
                    </tr>
"""
        html += """
                </tbody>
            </table>
"""

    html += """
        </div>
"""
    return html


def _render_decision_ev_analysis(decision_ev: dict, allin_ev: dict = None) -> str:
    """Render the Decision-Tree EV Analysis section.

    Shows per-street EV breakdown for fold/call/raise decisions,
    a bar chart of decision EV, top 5 EV leaks, and the all-in EV
    subsection (when available).
    """
    by_street = decision_ev.get('by_street', {})
    leaks = decision_ev.get('leaks', [])
    chart_data = decision_ev.get('chart_data', [])

    streets = ('preflop', 'flop', 'turn', 'river')
    street_labels = {
        'preflop': 'Preflop', 'flop': 'Flop',
        'turn': 'Turn', 'river': 'River',
    }

    html = """
        <div class="player-stats">
            <h2>EV Completo - Decision Tree</h2>
            <h3 class="section-subtitle">EV por Street e Tipo de Decis\u00e3o</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Street</th>
                        <th>Fold: Qtd</th>
                        <th>Fold: Net M\u00e9dio</th>
                        <th>Call: Qtd</th>
                        <th>Call: Net M\u00e9dio</th>
                        <th>Raise: Qtd</th>
                        <th>Raise: Net M\u00e9dio</th>
                    </tr>
                </thead>
                <tbody>
"""
    for street in streets:
        st_data = by_street.get(street, {})
        fold = st_data.get('fold', {})
        call = st_data.get('call', {})
        raise_ = st_data.get('raise', {})

        def _nc(v):
            return 'positive' if v >= 0 else 'negative'

        def _fmt(v):
            return f'${v:+.2f}' if v != 0 else '$0.00'

        f_avg = fold.get('avg_net', 0)
        c_avg = call.get('avg_net', 0)
        r_avg = raise_.get('avg_net', 0)

        html += f"""
                    <tr>
                        <td><strong>{street_labels[street]}</strong></td>
                        <td>{fold.get('count', 0)}</td>
                        <td class="{_nc(f_avg)}">{_fmt(f_avg)}</td>
                        <td>{call.get('count', 0)}</td>
                        <td class="{_nc(c_avg)}">{_fmt(c_avg)}</td>
                        <td>{raise_.get('count', 0)}</td>
                        <td class="{_nc(r_avg)}">{_fmt(r_avg)}</td>
                    </tr>
"""
    html += """
                </tbody>
            </table>
"""

    # Decision EV bar chart
    if chart_data:
        html += _render_decision_ev_chart(chart_data)

    # EV Leaks
    if leaks:
        html += """
            <h3 class="section-subtitle">Top EV Leaks</h3>
            <div class="leaks-container">
"""
        for i, leak in enumerate(leaks, 1):
            html += f"""
                <div class="leak-card">
                    <div class="leak-header">
                        <div class="leak-rank">#{i}</div>
                        <div class="leak-description">{leak['description']}</div>
                    </div>
                    <div class="leak-stats">
                        <span>Ocorr\u00eancias: <strong>{leak['count']}</strong></span>
                        <span>Net Total: <strong class="negative">${leak['total_loss']:.2f}</strong></span>
                        <span>M\u00e9dia/M\u00e3o: <strong class="negative">${leak['avg_loss']:.2f}</strong></span>
                    </div>
                    <div class="leak-suggestion">
                        {leak['suggestion']}
                    </div>
                </div>
"""
        html += """
            </div>
"""
    else:
        html += """
            <div style="padding:15px;color:#a0a0a0;text-align:center;">
                Dados insuficientes para identificar EV leaks (m\u00ednimo 5 m\u00e3os por spot)
            </div>
"""

    # All-in EV as sub-section
    if allin_ev and allin_ev.get('overall', {}).get('allin_hands', 0) > 0:
        html += """
            <h3 class="section-subtitle">EV Analysis (All-in Sub-se\u00e7\u00e3o)</h3>
"""
        html += _render_ev_analysis(
            allin_ev['overall'],
            allin_ev.get('by_stakes', {}),
            allin_ev.get('chart_data', []),
            _as_subsection=True,
        )

    html += """
        </div>
"""
    return html


def _render_decision_ev_chart(chart_data: list) -> str:
    """Render inline SVG bar chart of decision EV breakdown by street."""
    if not chart_data:
        return ''

    width = 700
    height = 300
    margin_top = 30
    margin_right = 20
    margin_bottom = 50
    margin_left = 70
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    # Collect all avg values for y-scale
    all_values = [0.0]
    for d in chart_data:
        all_values.extend([
            d.get('fold_avg', 0),
            d.get('call_avg', 0),
            d.get('raise_avg', 0),
        ])

    y_min = min(min(all_values), 0)
    y_max = max(max(all_values), 0)
    y_range = y_max - y_min if y_max != y_min else 1.0
    y_min -= y_range * 0.1
    y_max += y_range * 0.1
    y_range = y_max - y_min

    def scale_y(val):
        return margin_top + plot_h - ((val - y_min) / y_range) * plot_h

    zero_y = scale_y(0)

    num_streets = len(chart_data)
    group_w = plot_w / num_streets if num_streets > 0 else plot_w
    bar_w = group_w / 5  # 3 bars + 2 gaps
    colors = {'fold': '#ff6b6b', 'call': '#ffa500', 'raise': '#00ff88'}
    dec_order = ('fold', 'call', 'raise')

    street_labels = {
        'preflop': 'Pre', 'flop': 'Flop', 'turn': 'Turn', 'river': 'River',
    }

    bars_html = ''
    labels_html = ''
    for i, d in enumerate(chart_data):
        group_x = margin_left + i * group_w + group_w * 0.1
        street = d.get('street', '')
        label = street_labels.get(street, street)
        label_x = margin_left + (i + 0.5) * group_w
        labels_html += (
            f'<text x="{label_x:.1f}" y="{height - margin_bottom + 15}" '
            f'text-anchor="middle" fill="#888" font-size="11">{label}</text>\n'
        )
        for j, dec in enumerate(dec_order):
            val = d.get(f'{dec}_avg', 0)
            color = colors[dec]
            bar_x = group_x + j * (bar_w + 2)
            if val >= 0:
                bar_y = scale_y(val)
                bar_h = zero_y - bar_y
            else:
                bar_y = zero_y
                bar_h = scale_y(val) - zero_y
            if bar_h > 0:
                bars_html += (
                    f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" '
                    f'width="{bar_w:.1f}" height="{bar_h:.1f}" '
                    f'fill="{color}" opacity="0.8" rx="2"/>\n'
                )
            if abs(val) > 0.01:
                lbl_y = bar_y - 3 if val >= 0 else bar_y + bar_h + 10
                bars_html += (
                    f'<text x="{bar_x + bar_w / 2:.1f}" y="{lbl_y:.1f}" '
                    f'text-anchor="middle" fill="{color}" font-size="7">'
                    f'{val:+.1f}</text>\n'
                )

    # Grid lines and Y-axis labels
    grid_html = ''
    for i in range(6):
        y_val = y_min + (y_range * i / 5)
        y_pos = scale_y(y_val)
        grid_html += (
            f'<line x1="{margin_left}" y1="{y_pos:.1f}" '
            f'x2="{width - margin_right}" y2="{y_pos:.1f}" '
            f'stroke="rgba(255,255,255,0.1)" stroke-width="1"/>\n'
            f'<text x="{margin_left - 5}" y="{y_pos:.1f}" '
            f'text-anchor="end" fill="#888" font-size="10" '
            f'dominant-baseline="middle">${y_val:.1f}</text>\n'
        )

    zero_line = (
        f'<line x1="{margin_left}" y1="{zero_y:.1f}" '
        f'x2="{width - margin_right}" y2="{zero_y:.1f}" '
        f'stroke="rgba(255,255,255,0.4)" stroke-width="1.5" '
        f'stroke-dasharray="4,4"/>\n'
    )

    # Legend
    legend_x = width - margin_right - 110
    legend_html = (
        f'<rect x="{legend_x}" y="{margin_top}" width="100" height="55" '
        f'fill="rgba(0,0,0,0.5)" rx="5"/>\n'
    )
    dec_labels = {'fold': 'Fold', 'call': 'Call', 'raise': 'Raise'}
    for k, dec in enumerate(dec_order):
        color = colors[dec]
        ly = margin_top + 15 + k * 15
        legend_html += (
            f'<rect x="{legend_x + 8}" y="{ly - 6}" width="12" height="8" '
            f'fill="{color}" rx="2"/>\n'
            f'<text x="{legend_x + 25}" y="{ly}" fill="#e0e0e0" '
            f'font-size="10">{dec_labels[dec]}</text>\n'
        )

    svg = f"""
            <h3 class="section-subtitle">EV Breakdown por Tipo de Decis\u00e3o</h3>
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                 style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.2);border-radius:10px;margin:15px 0;">
                {grid_html}
                {zero_line}
                <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"
                      stroke="#555" stroke-width="1"/>
                {bars_html}
                {labels_html}
                {legend_html}
                <text x="15" y="{height / 2}" text-anchor="middle" fill="#888" font-size="11"
                      transform="rotate(-90, 15, {height / 2})">Net M\u00e9dio ($)</text>
            </svg>
"""
    return svg


def _render_ev_analysis(overall: dict, by_stakes: dict,
                        chart_data: list, _as_subsection: bool = False) -> str:
    """Render the EV Analysis HTML section with inline SVG chart."""

    luck = overall.get('luck_factor', 0)
    luck_class = 'positive' if luck >= 0 else 'negative'
    luck_label = 'acima do EV' if luck >= 0 else 'abaixo do EV'

    outer_open = '' if _as_subsection else '\n        <div class="player-stats">\n'
    heading = '' if _as_subsection else '            <h2>EV Analysis</h2>\n'
    outer_close = '' if _as_subsection else '\n        </div>\n'

    html = f"""{outer_open}{heading}            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">All-in Hands</div>
                    <div class="stat-value">{overall['allin_hands']}</div>
                    <div class="stat-detail">{overall['total_hands']} total</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">bb/100 Real</div>
                    <div class="stat-value {'positive' if overall['bb100_real'] >= 0 else 'negative'}">{overall['bb100_real']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">bb/100 EV-Adjusted</div>
                    <div class="stat-value {'positive' if overall['bb100_ev'] >= 0 else 'negative'}">{overall['bb100_ev']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Luck Factor</div>
                    <div class="stat-value {luck_class}">${luck:+.2f}</div>
                    <div class="stat-detail">{luck_label}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado Real</div>
                    <div class="stat-value {'positive' if overall['real_net'] >= 0 else 'negative'}">${overall['real_net']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado EV</div>
                    <div class="stat-value {'positive' if overall['ev_net'] >= 0 else 'negative'}">${overall['ev_net']:.2f}</div>
                </div>
            </div>
"""

    # SVG Chart: EV line vs Real line
    if chart_data and len(chart_data) >= 2:
        html += _render_ev_chart(chart_data)

    # Stakes breakdown table
    if by_stakes:
        html += """
            <h3 class="section-subtitle">Breakdown por Stakes</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Stakes</th>
                        <th>M\u00e3os</th>
                        <th>All-ins</th>
                        <th>bb/100 Real</th>
                        <th>bb/100 EV</th>
                        <th>Luck Factor</th>
                    </tr>
                </thead>
                <tbody>
"""
        for stakes, data in by_stakes.items():
            lf = data['luck_factor']
            lf_class = 'positive' if lf >= 0 else 'negative'
            r_class = 'positive' if data['bb100_real'] >= 0 else 'negative'
            e_class = 'positive' if data['bb100_ev'] >= 0 else 'negative'
            html += f"""
                    <tr>
                        <td><strong>{stakes}</strong></td>
                        <td>{data['total_hands']}</td>
                        <td>{data['allin_hands']}</td>
                        <td class="{r_class}">{data['bb100_real']:.2f}</td>
                        <td class="{e_class}">{data['bb100_ev']:.2f}</td>
                        <td class="{lf_class}">${lf:+.2f}</td>
                    </tr>
"""
        html += """
                </tbody>
            </table>
"""

    html += outer_close
    return html


def _render_ev_chart(chart_data: list) -> str:
    """Generate inline SVG chart for EV line vs Real line."""
    width = 700
    height = 300
    margin_top = 30
    margin_right = 20
    margin_bottom = 40
    margin_left = 70
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    # Data range
    all_values = ([d['real'] for d in chart_data]
                  + [d['ev'] for d in chart_data])
    y_min = min(all_values)
    y_max = max(all_values)
    x_max = chart_data[-1]['hand']

    # Add padding to y range
    y_range = y_max - y_min if y_max != y_min else 1.0
    y_min -= y_range * 0.1
    y_max += y_range * 0.1
    y_range = y_max - y_min

    def scale_x(hand):
        return (margin_left + (hand / x_max) * plot_w
                if x_max > 0 else margin_left)

    def scale_y(val):
        return margin_top + plot_h - ((val - y_min) / y_range) * plot_h

    # Build polyline points
    real_points = ' '.join(
        f'{scale_x(d["hand"]):.1f},{scale_y(d["real"]):.1f}'
        for d in chart_data)
    ev_points = ' '.join(
        f'{scale_x(d["hand"]):.1f},{scale_y(d["ev"]):.1f}'
        for d in chart_data)

    # Y-axis grid lines and labels
    num_gridlines = 5
    grid_html = ''
    for i in range(num_gridlines + 1):
        y_val = y_min + (y_range * i / num_gridlines)
        y_pos = scale_y(y_val)
        grid_html += (
            f'<line x1="{margin_left}" y1="{y_pos:.1f}" '
            f'x2="{width - margin_right}" y2="{y_pos:.1f}" '
            f'stroke="rgba(255,255,255,0.1)" stroke-width="1"/>\n'
            f'<text x="{margin_left - 5}" y="{y_pos:.1f}" '
            f'text-anchor="end" fill="#888" font-size="10" '
            f'dominant-baseline="middle">${y_val:.0f}</text>\n'
        )

    # Zero line
    zero_line = ''
    if y_min <= 0 <= y_max:
        zero_y = scale_y(0)
        zero_line = (
            f'<line x1="{margin_left}" y1="{zero_y:.1f}" '
            f'x2="{width - margin_right}" y2="{zero_y:.1f}" '
            f'stroke="rgba(255,255,255,0.3)" stroke-width="1" '
            f'stroke-dasharray="4,4"/>\n'
        )

    legend_x = width - margin_right - 140

    svg = f"""
            <h3 class="section-subtitle">EV Line vs Real Line</h3>
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                 style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.2);border-radius:10px;margin:15px 0;">
                {grid_html}
                {zero_line}
                <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"
                      stroke="#555" stroke-width="1"/>
                <line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"
                      stroke="#555" stroke-width="1"/>
                <text x="{width / 2}" y="{height - 5}" text-anchor="middle" fill="#888" font-size="11">M\u00e3os</text>
                <text x="15" y="{height / 2}" text-anchor="middle" fill="#888" font-size="11"
                      transform="rotate(-90, 15, {height / 2})">Profit ($)</text>
                <polyline points="{real_points}"
                          fill="none" stroke="#00ff88" stroke-width="2" stroke-linejoin="round"/>
                <polyline points="{ev_points}"
                          fill="none" stroke="#ffa500" stroke-width="2" stroke-linejoin="round"
                          stroke-dasharray="6,3"/>
                <rect x="{legend_x}" y="{margin_top}" width="130" height="45"
                      fill="rgba(0,0,0,0.5)" rx="5"/>
                <line x1="{legend_x + 10}" y1="{margin_top + 15}"
                      x2="{legend_x + 30}" y2="{margin_top + 15}"
                      stroke="#00ff88" stroke-width="2"/>
                <text x="{legend_x + 35}" y="{margin_top + 19}"
                      fill="#e0e0e0" font-size="11">Real</text>
                <line x1="{legend_x + 10}" y1="{margin_top + 35}"
                      x2="{legend_x + 30}" y2="{margin_top + 35}"
                      stroke="#ffa500" stroke-width="2" stroke-dasharray="6,3"/>
                <text x="{legend_x + 35}" y="{margin_top + 39}"
                      fill="#e0e0e0" font-size="11">EV-Adjusted</text>
            </svg>
"""
    return svg


def _render_leak_finder(leak_analysis: dict) -> str:
    """Render the Leak Finder section.

    Shows health score, top 5 leaks with priority badges,
    study spots, and period comparison.
    """
    health_score = leak_analysis.get('health_score', 100)
    top5 = leak_analysis.get('top5', [])
    study_spots = leak_analysis.get('study_spots', [])
    period = leak_analysis.get('period_comparison', {})
    total_leaks = leak_analysis.get('total_leaks', 0)

    html = """
        <div class="player-stats">
            <h2>Leak Finder</h2>
"""

    # Health score bar
    html += _render_health_score_bar(health_score, total_leaks)

    # Top 5 leaks
    if top5:
        html += """
            <h3 class="section-subtitle">Top 5 Leaks (maior impacto primeiro)</h3>
            <div class="leaks-container">
"""
        priority_labels = {0: 'URGENTE', 1: 'ALTO', 2: 'MÉDIO', 3: 'MÉDIO', 4: 'BAIXO'}
        priority_colors = {0: '#ff4444', 1: '#ff6b6b', 2: '#ffa500', 3: '#ffc107', 4: '#a0a0a0'}

        for i, leak in enumerate(top5):
            p_label = priority_labels.get(i, 'BAIXO')
            p_color = priority_colors.get(i, '#a0a0a0')
            cost = leak['cost_bb100']
            direction_label = '↑ acima' if leak['direction'] == 'too_high' else '↓ abaixo'
            cat_labels = {
                'preflop': 'Preflop', 'postflop': 'Postflop',
                'positional': 'Posicional', 'sizing': 'Sizing',
            }
            cat = cat_labels.get(leak['category'], leak['category'])

            html += f"""
                <div class="leak-card">
                    <div class="leak-header">
                        <div class="leak-rank">#{i + 1}</div>
                        <div class="leak-description">{leak['name']}</div>
                        <span class="badge" style="background:rgba({_hex_to_rgb(p_color)},0.2);color:{p_color};margin-left:auto;">{p_label}</span>
                    </div>
                    <div class="leak-stats">
                        <span>Categoria: <strong>{cat}</strong></span>
                        <span>Atual: <strong>{leak['current_value']:.1f}</strong></span>
                        <span>Ideal: <strong>{leak['healthy_low']:.0f}-{leak['healthy_high']:.0f}</strong></span>
                        <span>Custo: <strong class="negative">{cost:.2f} bb/100</strong></span>
                        <span>{direction_label} do range ideal</span>
                    </div>
                    <div class="leak-suggestion">
                        {leak['suggestion']}
                    </div>
                </div>
"""
        html += """
            </div>
"""

    # Study spots
    if study_spots:
        html += """
            <h3 class="section-subtitle">Spots para Estudar</h3>
            <div class="leaks-container">
"""
        for spot in study_spots:
            priority = spot.get('priority', 'média')
            if priority == 'alta':
                badge_class = 'badge-danger'
            elif priority == 'média':
                badge_class = 'badge-warning'
            else:
                badge_class = 'badge-good'

            html += f"""
                <div class="leak-card" style="border-color:rgba(0,170,255,0.25);background:rgba(0,170,255,0.05);">
                    <div class="leak-header">
                        <div class="leak-description" style="color:#66ccff;">{spot['title']}</div>
                        <span class="badge {badge_class}" style="margin-left:auto;">Prioridade: {priority}</span>
                    </div>
                    <div class="leak-suggestion">
                        {spot['action']}
                    </div>
                </div>
"""
        html += """
            </div>
"""

    # Period comparison
    if period and period.get('overall') and period.get('recent'):
        html += _render_period_comparison(period)

    html += """
        </div>
"""
    return html


def _render_health_score_bar(score: int, total_leaks: int) -> str:
    """Render visual health score meter (0-100)."""
    if score >= 80:
        color = '#00ff88'
        label = 'Excelente'
    elif score >= 60:
        color = '#ffc107'
        label = 'Bom'
    elif score >= 40:
        color = '#ffa500'
        label = 'Atenção'
    else:
        color = '#ff4444'
        label = 'Crítico'

    html = f"""
            <div style="margin:15px 0;">
                <div style="display:flex;align-items:center;gap:15px;margin-bottom:8px;">
                    <span style="color:#a0a0a0;font-size:0.9em;">Score de Saúde do Jogo</span>
                    <span style="font-size:1.5em;font-weight:bold;color:{color};">{score}/100</span>
                    <span class="badge" style="background:rgba({_hex_to_rgb(color)},0.2);color:{color};">{label}</span>
                    <span style="color:#a0a0a0;font-size:0.85em;">{total_leaks} leak(s) detectado(s)</span>
                </div>
                <div style="background:rgba(255,255,255,0.1);border-radius:10px;height:20px;overflow:hidden;">
                    <div style="background:{color};width:{score}%;height:100%;border-radius:10px;transition:width 0.3s;"></div>
                </div>
            </div>
"""
    return html


def _hex_to_rgb(hex_color: str) -> str:
    """Convert hex color like '#ff4444' to '255,68,68'."""
    h = hex_color.lstrip('#')
    return f'{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}'


def _render_period_comparison(period: dict) -> str:
    """Render period comparison table (last 30 days vs overall)."""
    overall = period.get('overall', {})
    recent = period.get('recent', {})
    period_label = period.get('period_label', 'Últimos 30 dias')

    stat_config = [
        ('vpip', 'VPIP', '{:.1f}%'),
        ('pfr', 'PFR', '{:.1f}%'),
        ('three_bet', '3-Bet', '{:.1f}%'),
        ('fold_to_3bet', 'Fold to 3-Bet', '{:.1f}%'),
        ('ats', 'ATS', '{:.1f}%'),
        ('af', 'AF', '{:.2f}'),
        ('wtsd', 'WTSD%', '{:.1f}%'),
        ('wsd', 'W$SD%', '{:.1f}%'),
        ('cbet', 'CBet%', '{:.1f}%'),
        ('fold_to_cbet', 'Fold to CBet', '{:.1f}%'),
        ('check_raise', 'Check-Raise%', '{:.1f}%'),
    ]

    html = f"""
            <h3 class="section-subtitle">Comparação de Períodos: Overall vs. {period_label}</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Stat</th>
                        <th>Overall</th>
                        <th>Recente</th>
                        <th>Variação</th>
                    </tr>
                </thead>
                <tbody>
"""
    for stat_key, label, fmt in stat_config:
        o_val = overall.get(stat_key)
        r_val = recent.get(stat_key)
        if o_val is None or r_val is None:
            continue
        diff = r_val - o_val
        diff_class = 'positive' if abs(diff) < 2 else ('negative' if abs(diff) > 5 else '')
        diff_str = f'{diff:+.1f}'
        html += f"""
                    <tr>
                        <td><strong>{label}</strong></td>
                        <td>{fmt.format(o_val)}</td>
                        <td>{fmt.format(r_val)}</td>
                        <td class="{diff_class}">{diff_str}</td>
                    </tr>
"""
    html += """
                </tbody>
            </table>
"""
    return html


def _render_positional_analysis(positional_stats: dict) -> str:
    """Render the full Positional Analysis section.

    Includes:
    - Main stats table: VPIP, PFR, 3-Bet, AF, CBet, WTSD, W$SD, win rate per position
    - Health badges per position (position-specific ranges)
    - Most profitable vs most deficitary comparison
    - ATS per steal position (CO, BTN, SB)
    - Blinds defense analysis (BB and SB)
    - Radar/spider chart showing player profile per position
    """
    by_position = positional_stats.get('by_position', {})
    if not by_position:
        return ''

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
    positions_present = [p for p in position_order if p in by_position]

    # ── Main Position Stats Table ──────────────────────────────────
    html = """
        <div class="player-stats">
            <h2>An\u00e1lise Posicional Completa</h2>
            <h3 class="section-subtitle">Stats por Posi\u00e7\u00e3o (VPIP, PFR, 3-Bet, AF, CBet, WTSD, W$SD, Win Rate)</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Posi\u00e7\u00e3o</th>
                        <th>M\u00e3os</th>
                        <th>VPIP</th>
                        <th>PFR</th>
                        <th>3-Bet</th>
                        <th>AF</th>
                        <th>CBet</th>
                        <th>WTSD</th>
                        <th>W$SD</th>
                        <th>$/m\u00e3o</th>
                        <th>bb/100</th>
                    </tr>
                </thead>
                <tbody>
"""
    for pos in positions_present:
        ps = by_position[pos]
        net_class = 'positive' if ps['net_per_hand'] >= 0 else 'negative'
        bb_class = 'positive' if ps['bb_per_100'] >= 0 else 'negative'
        html += f"""
                    <tr>
                        <td><strong>{pos}</strong></td>
                        <td>{ps['total_hands']}</td>
                        <td>
                            {ps['vpip']:.1f}%
                            {badge_html(ps['vpip_health'])}
                        </td>
                        <td>
                            {ps['pfr']:.1f}%
                            {badge_html(ps['pfr_health'])}
                        </td>
                        <td>
                            {ps['three_bet']:.1f}%
                            {badge_html(ps['three_bet_health'])}
                        </td>
                        <td>
                            {ps['af']:.2f}
                            {badge_html(ps['af_health'])}
                        </td>
                        <td>
                            {ps['cbet']:.1f}%
                            {badge_html(ps['cbet_health'])}
                        </td>
                        <td>
                            {ps['wtsd']:.1f}%
                            {badge_html(ps['wtsd_health'])}
                        </td>
                        <td>
                            {ps['wsd']:.1f}%
                            {badge_html(ps['wsd_health'])}
                        </td>
                        <td class="{net_class}">${ps['net_per_hand']:.3f}</td>
                        <td class="{bb_class}">{ps['bb_per_100']:+.1f}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
"""

    # ── Most Profitable vs Most Deficitary ──────────────────────────
    comparison = positional_stats.get('comparison', {})
    if comparison:
        most_p = comparison.get('most_profitable', {})
        most_d = comparison.get('most_deficitary', {})
        html += f"""
            <h3 class="section-subtitle">Posi\u00e7\u00e3o mais Lucrativa vs. mais Deficit\u00e1ria</h3>
            <div class="stats-grid" style="grid-template-columns:1fr 1fr;">
                <div class="stat-card" style="border-left:4px solid #00ff88;">
                    <div class="stat-label">Mais Lucrativa</div>
                    <div class="stat-value positive">{most_p.get('position', '-')}</div>
                    <div class="stat-detail">{most_p.get('bb_per_100', 0):+.1f} bb/100 ({most_p.get('total_hands', 0)} m\u00e3os)</div>
                    <div class="stat-detail">VPIP {most_p.get('vpip', 0):.1f}% | PFR {most_p.get('pfr', 0):.1f}%</div>
                </div>
                <div class="stat-card" style="border-left:4px solid #ff4444;">
                    <div class="stat-label">Mais Deficit\u00e1ria</div>
                    <div class="stat-value negative">{most_d.get('position', '-')}</div>
                    <div class="stat-detail">{most_d.get('bb_per_100', 0):+.1f} bb/100 ({most_d.get('total_hands', 0)} m\u00e3os)</div>
                    <div class="stat-detail">VPIP {most_d.get('vpip', 0):.1f}% | PFR {most_d.get('pfr', 0):.1f}%</div>
                </div>
            </div>
"""

    # ── ATS per Steal Position ──────────────────────────────────────
    ats_by_pos = positional_stats.get('ats_by_pos', {})
    if ats_by_pos:
        html += """
            <h3 class="section-subtitle">ATS (Attempt to Steal) por Posi\u00e7\u00e3o de Steal</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Posi\u00e7\u00e3o</th>
                        <th>Oportunidades</th>
                        <th>Steals</th>
                        <th>ATS%</th>
                    </tr>
                </thead>
                <tbody>
"""
        for pos in ('CO', 'BTN', 'SB'):
            if pos not in ats_by_pos:
                continue
            ad = ats_by_pos[pos]
            html += f"""
                    <tr>
                        <td><strong>{pos}</strong></td>
                        <td>{ad['ats_opps']}</td>
                        <td>{ad['ats_count']}</td>
                        <td>{ad['ats']:.1f}%</td>
                    </tr>
"""
        html += """
                </tbody>
            </table>
"""

    # ── Blinds Defense Analysis ──────────────────────────────────────
    blinds_defense = positional_stats.get('blinds_defense', {})
    if blinds_defense:
        html += """
            <h3 class="section-subtitle">Defesa das Blinds (BB e SB vs. Steal)</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Posi\u00e7\u00e3o</th>
                        <th>Situa\u00e7\u00f5es de Steal</th>
                        <th>Fold to Steal%</th>
                        <th>3-Bet vs Steal%</th>
                        <th>Call vs Steal%</th>
                    </tr>
                </thead>
                <tbody>
"""
        for pos in ('BB', 'SB'):
            if pos not in blinds_defense:
                continue
            bd = blinds_defense[pos]
            html += f"""
                    <tr>
                        <td><strong>{pos}</strong></td>
                        <td>{bd['steal_opps']}</td>
                        <td>{bd['fold_to_steal']:.1f}% ({bd['fold_to_steal_count']})</td>
                        <td>{bd['three_bet_vs_steal']:.1f}% ({bd['three_bet_vs_steal_count']})</td>
                        <td>{bd['call_vs_steal']:.1f}% ({bd['call_vs_steal_count']})</td>
                    </tr>
"""
        html += """
                </tbody>
            </table>
"""

    # ── Radar Chart ──────────────────────────────────────────────────
    radar_data = positional_stats.get('radar', [])
    if radar_data:
        html += _render_radar_chart(radar_data)

    html += """
        </div>
"""
    return html


def _render_radar_chart(radar_data: list) -> str:
    """Render inline SVG radar/spider chart showing player profile per position.

    Each position is plotted as a polygon on 7 normalized axes:
    VPIP, PFR, 3-Bet, AF, CBet, WTSD, W$SD (each 0-100 normalized).
    """
    import math

    axes = ['vpip', 'pfr', 'three_bet', 'af', 'cbet', 'wtsd', 'wsd']
    axis_labels = ['VPIP', 'PFR', '3-Bet', 'AF', 'CBet', 'WTSD', 'W$SD']
    n_axes = len(axes)

    width = 500
    height = 400
    cx = width // 2
    cy = height // 2 - 10
    radius = 140
    label_r = radius + 22

    def angle(i):
        return math.pi / 2 - (2 * math.pi * i / n_axes)

    def polar(r, i):
        a = angle(i)
        return cx + r * math.cos(a), cy - r * math.sin(a)

    svg = f'''
            <h3 class="section-subtitle">Radar: Perfil do Jogador por Posi\u00e7\u00e3o</h3>
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                 style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.2);border-radius:10px;margin:15px 0;">
'''

    # Draw grid polygons
    for level in (20, 40, 60, 80, 100):
        r = radius * level / 100
        pts = ' '.join(f'{polar(r, i)[0]:.1f},{polar(r, i)[1]:.1f}' for i in range(n_axes))
        svg += f'        <polygon points="{pts}" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="0.8"/>\n'
        lx, ly = polar(r, 0)
        svg += f'        <text x="{lx + 3:.1f}" y="{ly:.1f}" fill="#666" font-size="8">{level}%</text>\n'

    # Draw axis lines
    for i in range(n_axes):
        x1, y1 = polar(0, i)
        x2, y2 = polar(radius, i)
        svg += f'        <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="rgba(255,255,255,0.15)" stroke-width="0.8"/>\n'

    # Draw axis labels
    for i, label in enumerate(axis_labels):
        lx, ly = polar(label_r, i)
        svg += f'        <text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" fill="#b0b0b0" font-size="10">{label}</text>\n'

    # Color palette for positions
    pos_stroke = {
        'UTG': '#ff6464', 'UTG+1': '#ff8c64',
        'MP': '#ffc832', 'MP+1': '#c8ff32',
        'HJ': '#64ff64', 'CO': '#32ffc8',
        'BTN': '#00aaff', 'SB': '#b464ff',
        'BB': '#ff64c8',
    }
    pos_fill = {
        'UTG': 'rgba(255,100,100,0.25)', 'UTG+1': 'rgba(255,140,100,0.25)',
        'MP': 'rgba(255,200,50,0.25)', 'MP+1': 'rgba(200,255,50,0.25)',
        'HJ': 'rgba(100,255,100,0.25)', 'CO': 'rgba(50,255,200,0.25)',
        'BTN': 'rgba(0,170,255,0.25)', 'SB': 'rgba(180,100,255,0.25)',
        'BB': 'rgba(255,100,200,0.25)',
    }

    # Draw position polygons
    for entry in radar_data:
        pos = entry['position']
        vals = entry['values']
        pts_list = []
        for i, key in enumerate(axes):
            r = radius * vals.get(key, 0) / 100
            px, py = polar(r, i)
            pts_list.append(f'{px:.1f},{py:.1f}')
        pts = ' '.join(pts_list)
        fill = pos_fill.get(pos, 'rgba(200,200,200,0.25)')
        stroke = pos_stroke.get(pos, '#ccc')
        svg += (
            f'        <polygon points="{pts}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5"/>\n'
        )

    # Legend
    legend_x = width - 95
    legend_y = 30
    svg += f'        <rect x="{legend_x - 5}" y="{legend_y - 5}" width="95" height="{len(radar_data) * 16 + 10}" fill="rgba(0,0,0,0.5)" rx="4"/>\n'
    for k, entry in enumerate(radar_data):
        pos = entry['position']
        bb = entry['bb_per_100']
        color = pos_stroke.get(pos, '#ccc')
        ly = legend_y + k * 16
        svg += f'        <rect x="{legend_x}" y="{ly}" width="10" height="10" fill="{color}"/>\n'
        bb_str = f'{bb:+.0f}'
        svg += f'        <text x="{legend_x + 13}" y="{ly + 9}" fill="#c0c0c0" font-size="9">{pos} ({bb_str})</text>\n'

    svg += '            </svg>\n'
    return svg


# ── Stack Depth Analysis ──────────────────────────────────────────────────────

def _render_stack_depth_analysis(stack_depth_data: dict) -> str:
    """Render the Stack Depth Analysis section.

    Includes:
    - Stats table per stack tier (deep/medium/shallow/shove-zone)
    - Health badges using tier-specific ranges
    - Position x tier cross-table (VPIP, PFR, bb/100)
    - Win rate per tier
    - Coverage summary (how many hands had known stack)
    """
    by_tier = stack_depth_data.get('by_tier', {})
    if not by_tier:
        return ''

    tier_order = stack_depth_data.get('tier_order', ['deep', 'medium', 'shallow', 'shove'])
    tiers_present = [t for t in tier_order if t in by_tier]
    hands_with_stack = stack_depth_data.get('hands_with_stack', 0)
    hands_total = stack_depth_data.get('hands_total', 0)

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    coverage_pct = (hands_with_stack / hands_total * 100) if hands_total > 0 else 0

    html = f"""
        <div class="player-stats">
            <h2>An\u00e1lise por Stack Depth (BB Count)</h2>
            <h3 class="section-subtitle">Stats Segmentadas por Profundidade de Stack</h3>
            <p style="color:#a0a0a0; margin-bottom:15px;">
                {hands_with_stack} de {hands_total} m\u00e3os com stack inicial conhecido ({coverage_pct:.0f}%)
            </p>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Stack Tier</th>
                        <th>M\u00e3os</th>
                        <th>VPIP</th>
                        <th>PFR</th>
                        <th>3-Bet</th>
                        <th>AF</th>
                        <th>CBet</th>
                        <th>WTSD</th>
                        <th>W$SD</th>
                        <th>$/m\u00e3o</th>
                        <th>bb/100</th>
                    </tr>
                </thead>
                <tbody>
"""
    for tier in tiers_present:
        ts = by_tier[tier]
        net_class = 'positive' if ts['net_per_hand'] >= 0 else 'negative'
        bb_class = 'positive' if ts['bb_per_100'] >= 0 else 'negative'
        html += f"""
                    <tr>
                        <td><strong>{ts['label']}</strong></td>
                        <td>{ts['total_hands']}</td>
                        <td>
                            {ts['vpip']:.1f}%
                            {badge_html(ts['vpip_health'])}
                        </td>
                        <td>
                            {ts['pfr']:.1f}%
                            {badge_html(ts['pfr_health'])}
                        </td>
                        <td>
                            {ts['three_bet']:.1f}%
                            {badge_html(ts['three_bet_health'])}
                        </td>
                        <td>
                            {ts['af']:.2f}
                            {badge_html(ts['af_health'])}
                        </td>
                        <td>
                            {ts['cbet']:.1f}%
                            {badge_html(ts['cbet_health'])}
                        </td>
                        <td>
                            {ts['wtsd']:.1f}%
                            {badge_html(ts['wtsd_health'])}
                        </td>
                        <td>
                            {ts['wsd']:.1f}%
                            {badge_html(ts['wsd_health'])}
                        </td>
                        <td class="{net_class}">${ts['net_per_hand']:.3f}</td>
                        <td class="{bb_class}">{ts['bb_per_100']:+.1f}</td>
                    </tr>
"""

    html += """
                </tbody>
            </table>
"""

    # ── Position x Stack Tier cross-table ──────────────────────────────
    by_position_tier = stack_depth_data.get('by_position_tier', {})
    if by_position_tier:
        html += """
            <h3 class="section-subtitle">VPIP e PFR por Posi\u00e7\u00e3o x Stack Depth</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Posi\u00e7\u00e3o</th>
"""
        for tier in tiers_present:
            label = by_tier[tier]['label']
            html += f'                        <th colspan="2">{label}</th>\n'

        html += """                    </tr>
                    <tr>
                        <th></th>
"""
        for _ in tiers_present:
            html += '                        <th>VPIP</th><th>PFR</th>\n'
        html += '                    </tr>\n                </thead>\n                <tbody>\n'

        position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
        for pos in position_order:
            if pos not in by_position_tier:
                continue
            pos_tiers = by_position_tier[pos]
            html += f'                    <tr>\n                        <td><strong>{pos}</strong></td>\n'
            for tier in tiers_present:
                if tier in pos_tiers:
                    pt = pos_tiers[tier]
                    html += f'                        <td>{pt["vpip"]:.1f}%</td>'
                    html += f'<td>{pt["pfr"]:.1f}%</td>\n'
                else:
                    html += '                        <td>—</td><td>—</td>\n'
            html += '                    </tr>\n'

        html += """
                </tbody>
            </table>
"""

    html += """
        </div>
"""
    return html


# ── VPIP Drill-Down Modal ─────────────────────────────────────────────────────

def _render_vpip_modal(positional_stats: dict, stack_depth_data: dict) -> str:
    """Render the hidden VPIP drill-down modal with two tabs.

    Tab 1 – Por Posição: VPIP breakdown by position (from US-010 data).
    Tab 2 – Por Stack Depth: VPIP breakdown by stack tier (from US-017 data).

    The modal is opened by clicking the VPIP stat card via openVpipModal()
    and closed by the ✕ button, backdrop click, or the ESC key.
    """
    position_order = ['UTG', 'UTG+1', 'MP', 'MP+1', 'HJ', 'CO', 'BTN', 'SB', 'BB']
    by_position = positional_stats.get('by_position', {})
    by_tier = stack_depth_data.get('by_tier', {})
    tier_order = stack_depth_data.get('tier_order', ['deep', 'medium', 'shallow', 'shove'])
    tiers_present = [t for t in tier_order if t in by_tier]

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    # ── Panel 1: by position ─────────────────────────────────────────────
    pos_rows = ''
    for pos in position_order:
        if pos not in by_position:
            continue
        ps = by_position[pos]
        pos_rows += f"""
                    <tr>
                        <td><strong>{pos}</strong></td>
                        <td>{ps['total_hands']}</td>
                        <td>{ps['vpip']:.1f}% {badge_html(ps.get('vpip_health', 'good'))}</td>
                        <td>{ps['pfr']:.1f}%</td>
                        <td>{ps['three_bet']:.1f}%</td>
                        <td class="{'positive' if ps.get('bb_per_100', 0) >= 0 else 'negative'}">{ps.get('bb_per_100', 0):+.1f}</td>
                    </tr>"""

    if pos_rows:
        position_table = f"""
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Posi\u00e7\u00e3o</th>
                        <th>M\u00e3os</th>
                        <th>VPIP</th>
                        <th>PFR</th>
                        <th>3-Bet</th>
                        <th>bb/100</th>
                    </tr>
                </thead>
                <tbody>{pos_rows}
                </tbody>
            </table>"""
    else:
        position_table = '<p style="color:#a0a0a0;">Sem dados por posi\u00e7\u00e3o dispon\u00edveis.</p>'

    # ── Panel 2: by stack tier ────────────────────────────────────────────
    tier_rows = ''
    for tier in tiers_present:
        ts = by_tier[tier]
        tier_rows += f"""
                    <tr>
                        <td><strong>{ts['label']}</strong></td>
                        <td>{ts['total_hands']}</td>
                        <td>{ts['vpip']:.1f}% {badge_html(ts.get('vpip_health', 'good'))}</td>
                        <td>{ts['pfr']:.1f}% {badge_html(ts.get('pfr_health', 'good'))}</td>
                        <td>{ts['three_bet']:.1f}%</td>
                        <td class="{'positive' if ts.get('bb_per_100', 0) >= 0 else 'negative'}">{ts.get('bb_per_100', 0):+.1f}</td>
                    </tr>"""

    if tier_rows:
        stack_table = f"""
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Stack Tier</th>
                        <th>M\u00e3os</th>
                        <th>VPIP</th>
                        <th>PFR</th>
                        <th>3-Bet</th>
                        <th>bb/100</th>
                    </tr>
                </thead>
                <tbody>{tier_rows}
                </tbody>
            </table>"""
    else:
        stack_table = '<p style="color:#a0a0a0;">Sem dados por stack depth dispon\u00edveis.</p>'

    return f"""
    <!-- VPIP Drill-Down Modal (US-018) -->
    <div id="vpip-modal-overlay" class="vpip-modal-overlay" onclick="closeVpipModalOverlay(event)">
        <div id="vpip-modal" class="vpip-modal" role="dialog" aria-modal="true" aria-labelledby="vpip-modal-title">
            <div class="vpip-modal-header">
                <span id="vpip-modal-title" class="vpip-modal-title">&#128269; VPIP Drill-Down</span>
                <button class="vpip-modal-close" onclick="closeVpipModal()" aria-label="Fechar">&times;</button>
            </div>
            <div class="vpip-tab-bar">
                <button id="vpip-tab-btn-position" class="vpip-tab-btn active"
                        onclick="switchVpipTab('position')">Por Posi\u00e7\u00e3o</button>
                <button id="vpip-tab-btn-stack" class="vpip-tab-btn"
                        onclick="switchVpipTab('stack')">Por Stack Depth</button>
            </div>
            <div id="vpip-panel-position" class="vpip-panel active">
                <h3 class="section-subtitle" style="margin-top:0;">VPIP por Posi\u00e7\u00e3o</h3>
                {position_table}
            </div>
            <div id="vpip-panel-stack" class="vpip-panel">
                <h3 class="section-subtitle" style="margin-top:0;">VPIP por Stack Depth</h3>
                {stack_table}
            </div>
        </div>
    </div>"""


# ── Red Line / Blue Line ──────────────────────────────────────────────────────

def _render_redline_blueline_chart(chart_data: list) -> str:
    """Generate 3-line SVG chart: total (green), showdown (blue), non-showdown (red)."""
    width = 700
    height = 300
    margin_top = 30
    margin_right = 20
    margin_bottom = 40
    margin_left = 70
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    all_values = (
        [d['total'] for d in chart_data]
        + [d['showdown'] for d in chart_data]
        + [d['nonshowdown'] for d in chart_data]
    )
    y_min = min(all_values)
    y_max = max(all_values)
    x_max = chart_data[-1]['hand']

    y_range = y_max - y_min if y_max != y_min else 1.0
    y_min -= y_range * 0.1
    y_max += y_range * 0.1
    y_range = y_max - y_min

    def scale_x(hand):
        return margin_left + (hand / x_max) * plot_w if x_max > 0 else margin_left

    def scale_y(val):
        return margin_top + plot_h - ((val - y_min) / y_range) * plot_h

    total_pts = ' '.join(
        f'{scale_x(d["hand"]):.1f},{scale_y(d["total"]):.1f}' for d in chart_data
    )
    sd_pts = ' '.join(
        f'{scale_x(d["hand"]):.1f},{scale_y(d["showdown"]):.1f}' for d in chart_data
    )
    nsd_pts = ' '.join(
        f'{scale_x(d["hand"]):.1f},{scale_y(d["nonshowdown"]):.1f}' for d in chart_data
    )

    num_gridlines = 5
    grid_html = ''
    for i in range(num_gridlines + 1):
        y_val = y_min + (y_range * i / num_gridlines)
        y_pos = scale_y(y_val)
        grid_html += (
            f'<line x1="{margin_left}" y1="{y_pos:.1f}" '
            f'x2="{width - margin_right}" y2="{y_pos:.1f}" '
            f'stroke="rgba(255,255,255,0.1)" stroke-width="1"/>\n'
            f'<text x="{margin_left - 5}" y="{y_pos:.1f}" '
            f'text-anchor="end" fill="#888" font-size="10" '
            f'dominant-baseline="middle">${y_val:.0f}</text>\n'
        )

    zero_line = ''
    if y_min <= 0 <= y_max:
        zero_y = scale_y(0)
        zero_line = (
            f'<line x1="{margin_left}" y1="{zero_y:.1f}" '
            f'x2="{width - margin_right}" y2="{zero_y:.1f}" '
            f'stroke="rgba(255,255,255,0.3)" stroke-width="1" stroke-dasharray="4,4"/>\n'
        )

    legend_x = width - margin_right - 180

    return f"""
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                 style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.2);border-radius:10px;margin:15px 0;">
                {grid_html}
                {zero_line}
                <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"
                      stroke="#555" stroke-width="1"/>
                <line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"
                      stroke="#555" stroke-width="1"/>
                <text x="{width / 2}" y="{height - 5}" text-anchor="middle" fill="#888" font-size="11">M\u00e3os</text>
                <text x="15" y="{height / 2}" text-anchor="middle" fill="#888" font-size="11"
                      transform="rotate(-90, 15, {height / 2})">Profit ($)</text>
                <polyline points="{total_pts}"
                          fill="none" stroke="#00ff88" stroke-width="2" stroke-linejoin="round"/>
                <polyline points="{sd_pts}"
                          fill="none" stroke="#4488ff" stroke-width="2" stroke-linejoin="round"/>
                <polyline points="{nsd_pts}"
                          fill="none" stroke="#ff4444" stroke-width="2" stroke-linejoin="round"/>
                <rect x="{legend_x}" y="{margin_top}" width="170" height="65"
                      fill="rgba(0,0,0,0.5)" rx="5"/>
                <line x1="{legend_x + 10}" y1="{margin_top + 15}" x2="{legend_x + 30}" y2="{margin_top + 15}"
                      stroke="#00ff88" stroke-width="2"/>
                <text x="{legend_x + 35}" y="{margin_top + 19}" fill="#e0e0e0" font-size="11">Total (Green)</text>
                <line x1="{legend_x + 10}" y1="{margin_top + 35}" x2="{legend_x + 30}" y2="{margin_top + 35}"
                      stroke="#4488ff" stroke-width="2"/>
                <text x="{legend_x + 35}" y="{margin_top + 39}" fill="#e0e0e0" font-size="11">Showdown (Blue)</text>
                <line x1="{legend_x + 10}" y1="{margin_top + 55}" x2="{legend_x + 30}" y2="{margin_top + 55}"
                      stroke="#ff4444" stroke-width="2"/>
                <text x="{legend_x + 35}" y="{margin_top + 59}" fill="#e0e0e0" font-size="11">N\u00e3o-Showdown (Red)</text>
            </svg>
"""


def _render_redline_blueline(data: dict) -> str:
    """Render the Red Line / Blue Line analysis section."""
    if not data or data.get('total_hands', 0) < 2:
        return ''

    total_hands = data['total_hands']
    showdown_hands = data['showdown_hands']
    nonshowdown_hands = data['nonshowdown_hands']
    showdown_net = data['showdown_net']
    nonshowdown_net = data['nonshowdown_net']
    total_net = data['total_net']
    chart_data = data.get('chart_data', [])
    diagnostics = data.get('diagnostics', [])
    by_session = data.get('by_session', [])

    sd_pct = (showdown_hands / total_hands * 100) if total_hands > 0 else 0
    nsd_pct = (nonshowdown_hands / total_hands * 100) if total_hands > 0 else 0
    sd_class = 'positive' if showdown_net >= 0 else 'negative'
    nsd_class = 'positive' if nonshowdown_net >= 0 else 'negative'
    total_class = 'positive' if total_net >= 0 else 'negative'

    html = """
        <div class="summary" style="margin-bottom:20px;">
            <h2 style="color:#00ff88;margin-bottom:15px;">Red Line / Blue Line</h2>
            <p style="color:#a0a0a0;font-size:0.9em;margin-bottom:15px;">
                An\u00e1lise cumulativa de lucro por tipo de resultado.
                <strong style="color:#4488ff;">Blue line</strong> = m\u00e3os com showdown,
                <strong style="color:#ff4444;">Red line</strong> = m\u00e3os sem showdown,
                <strong style="color:#00ff88;">Green line</strong> = total.
            </p>
"""
    html += f"""            <div class="summary-grid">
                <div class="stat-card">
                    <div class="stat-label">Total de M\u00e3os</div>
                    <div class="stat-value">{total_hands}</div>
                </div>
                <div class="stat-card" style="background:rgba(68,136,255,0.1);">
                    <div class="stat-label">M\u00e3os Showdown</div>
                    <div class="stat-value">{showdown_hands} <span style="font-size:0.7em;color:#888;">({sd_pct:.1f}%)</span></div>
                    <div class="stat-detail {sd_class}">${showdown_net:+.2f}</div>
                </div>
                <div class="stat-card" style="background:rgba(255,68,68,0.1);">
                    <div class="stat-label">M\u00e3os Sem Showdown</div>
                    <div class="stat-value">{nonshowdown_hands} <span style="font-size:0.7em;color:#888;">({nsd_pct:.1f}%)</span></div>
                    <div class="stat-detail {nsd_class}">${nonshowdown_net:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Blue Line Net</div>
                    <div class="stat-value {sd_class}">${showdown_net:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Red Line Net</div>
                    <div class="stat-value {nsd_class}">${nonshowdown_net:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Net</div>
                    <div class="stat-value {total_class}">${total_net:+.2f}</div>
                </div>
            </div>
"""
    if chart_data and len(chart_data) >= 2:
        html += '            <h3 class="section-subtitle" style="margin-top:20px;">Evolu\u00e7\u00e3o Cumulativa</h3>\n'
        html += _render_redline_blueline_chart(chart_data)

    if diagnostics:
        html += '            <div style="margin-top:15px;">\n'
        html += '                <h4 style="color:#00ff88;margin-bottom:10px;">Diagn\u00f3stico Autom\u00e1tico</h4>\n'
        for d in diagnostics:
            if d['type'] == 'good':
                color = '#00ff88'
                bg = 'rgba(0,255,136,0.1)'
            elif d['type'] == 'warning':
                color = '#ffa500'
                bg = 'rgba(255,165,0,0.1)'
            else:
                color = '#ff4444'
                bg = 'rgba(255,68,68,0.1)'
            html += (
                f'                <div style="background:{bg};border:1px solid {color};'
                f'border-radius:8px;padding:10px;margin-bottom:8px;">\n'
                f'                    <strong style="color:{color};">{d["title"]}</strong>\n'
                f'                    <p style="color:#c0c0c0;font-size:0.9em;margin-top:4px;">'
                f'{d["message"]}</p>\n'
                f'                </div>\n'
            )
        html += '            </div>\n'

    session_rows = [s for s in by_session if s.get('hands', 0) > 0]
    if session_rows:
        html += """            <div style="margin-top:15px;">
                <h4 style="color:#00ff88;margin-bottom:10px;">Breakdown por Sess\u00e3o</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Data</th>
                            <th>M\u00e3os</th>
                            <th>Showdown</th>
                            <th>Sem Showdown</th>
                            <th>Blue Net</th>
                            <th>Red Net</th>
                            <th>Total</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        for s in session_rows:
            sd_c = 'positive' if s['showdown_net'] >= 0 else 'negative'
            nsd_c = 'positive' if s['nonshowdown_net'] >= 0 else 'negative'
            tot_c = 'positive' if s['total_net'] >= 0 else 'negative'
            html += (
                f'                        <tr>'
                f'<td>{s.get("date", "")}</td>'
                f'<td>{s["hands"]}</td>'
                f'<td>{s["showdown_hands"]}</td>'
                f'<td>{s["nonshowdown_hands"]}</td>'
                f'<td class="{sd_c}">${s["showdown_net"]:+.2f}</td>'
                f'<td class="{nsd_c}">${s["nonshowdown_net"]:+.2f}</td>'
                f'<td class="{tot_c}">${s["total_net"]:+.2f}</td>'
                f'</tr>\n'
            )
        html += """                    </tbody>
                </table>
            </div>
"""

    html += """        </div>
"""
    return html


# ── Bet Sizing & Pot-Type Segmentation ───────────────────────────────────────

def _render_bet_sizing_analysis(data: dict) -> str:
    """Render the Bet Sizing & Pot-Type Segmentation HTML section."""
    if not data or data.get('total_hands', 0) < 5:
        return ''

    total_hands = data['total_hands']
    pot_types = data.get('pot_types', {})
    sizing = data.get('sizing', {})
    hum = data.get('hu_vs_multiway', {})
    diagnostics = data.get('diagnostics', [])

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    def wr_class(val: float) -> str:
        return 'positive' if val >= 0 else 'negative'

    html = f"""
        <div class="summary" style="margin-bottom:20px;">
            <h2 style="color:#00ff88;margin-bottom:15px;">Bet Sizing & Pot-Type Segmentation</h2>
            <p style="color:#a0a0a0;font-size:0.9em;margin-bottom:15px;">
                Classifica\u00e7\u00e3o por tipo de pote e an\u00e1lise de sizing.
                Total de <strong>{total_hands}</strong> m\u00e3os analisadas.
            </p>
"""

    # ── Pot-type stats table ──
    pt_labels = [
        ('limped', 'Limped'),
        ('srp', 'SRP'),
        ('3bet', '3-bet'),
        ('4bet_plus', '4-bet+'),
    ]
    html += """            <h3 style="color:#00ff88;margin-bottom:10px;">Stats por Tipo de Pote</h3>
            <table>
                <thead>
                    <tr>
                        <th>Tipo</th>
                        <th>M\u00e3os</th>
                        <th>HU</th>
                        <th>Multi</th>
                        <th>VPIP%</th>
                        <th>PFR%</th>
                        <th>AF</th>
                        <th>CBet%</th>
                        <th>WTSD%</th>
                        <th>W$SD%</th>
                        <th>Win Rate</th>
                        <th>Sa\u00fade</th>
                    </tr>
                </thead>
                <tbody>
"""
    for key, label in pt_labels:
        pt = pot_types.get(key, {})
        h = pt.get('hands', 0)
        if h == 0:
            html += f"""                    <tr>
                        <td><strong>{label}</strong></td>
                        <td colspan="11" style="color:#666;">Sem dados</td>
                    </tr>
"""
            continue
        wr = pt.get('win_rate_bb100', 0)
        wrc = wr_class(wr)
        health = pt.get('health', 'good')
        html += (
            f'                    <tr>\n'
            f'                        <td><strong>{label}</strong></td>\n'
            f'                        <td>{h}</td>\n'
            f'                        <td>{pt.get("hu_hands", 0)}</td>\n'
            f'                        <td>{pt.get("multiway_hands", 0)}</td>\n'
            f'                        <td>{pt.get("vpip", 0):.1f}%</td>\n'
            f'                        <td>{pt.get("pfr", 0):.1f}%</td>\n'
            f'                        <td>{pt.get("af", 0):.2f}</td>\n'
            f'                        <td>{pt.get("cbet", 0):.1f}%</td>\n'
            f'                        <td>{pt.get("wtsd", 0):.1f}%</td>\n'
            f'                        <td>{pt.get("wsd", 0):.1f}%</td>\n'
            f'                        <td class="{wrc}">{wr:+.1f} bb/100</td>\n'
            f'                        <td>{badge_html(health)}</td>\n'
            f'                    </tr>\n'
        )
    html += """                </tbody>
            </table>
"""

    # ── HU vs Multiway ──
    hu = hum.get('heads_up', {})
    mw = hum.get('multiway', {})
    if hu.get('hands', 0) > 0 or mw.get('hands', 0) > 0:
        html += """            <h3 style="color:#00ff88;margin:20px 0 10px;">Heads-Up vs Multiway</h3>
            <table>
                <thead>
                    <tr>
                        <th>Tipo</th>
                        <th>M\u00e3os</th>
                        <th>VPIP%</th>
                        <th>PFR%</th>
                        <th>AF</th>
                        <th>WTSD%</th>
                        <th>W$SD%</th>
                        <th>Win Rate</th>
                        <th>Sa\u00fade</th>
                    </tr>
                </thead>
                <tbody>
"""
        for seg_label, seg in [('Heads-Up', hu), ('Multiway', mw)]:
            h = seg.get('hands', 0)
            if h == 0:
                continue
            wr = seg.get('win_rate_bb100', 0)
            wrc = wr_class(wr)
            health = seg.get('health', 'good')
            html += (
                f'                    <tr>\n'
                f'                        <td><strong>{seg_label}</strong></td>\n'
                f'                        <td>{h}</td>\n'
                f'                        <td>{seg.get("vpip", 0):.1f}%</td>\n'
                f'                        <td>{seg.get("pfr", 0):.1f}%</td>\n'
                f'                        <td>{seg.get("af", 0):.2f}</td>\n'
                f'                        <td>{seg.get("wtsd", 0):.1f}%</td>\n'
                f'                        <td>{seg.get("wsd", 0):.1f}%</td>\n'
                f'                        <td class="{wrc}">{wr:+.1f} bb/100</td>\n'
                f'                        <td>{badge_html(health)}</td>\n'
                f'                    </tr>\n'
            )
        html += """                </tbody>
            </table>
"""

    # ── Sizing distributions ──
    sizing_sections = [
        ('preflop', 'Preflop Raise Size (múltiplos de BB)'),
        ('flop', 'Flop Bet Size (% do pote)'),
        ('turn', 'Turn Bet Size (% do pote)'),
        ('river', 'River Bet Size (% do pote)'),
    ]
    has_sizing = any(sizing.get(s, {}).get('samples', 0) > 0 for s, _ in sizing_sections)
    if has_sizing:
        html += '            <h3 style="color:#00ff88;margin:20px 0 10px;">Distribui\u00e7\u00e3o de Bet Sizing</h3>\n'
        html += '            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:15px;">\n'
        for street_key, street_label in sizing_sections:
            sd = sizing.get(street_key, {})
            samples = sd.get('samples', 0)
            if samples == 0:
                continue
            avg = sd.get('avg', 0)
            median = sd.get('median', 0)
            unit = 'x BB' if street_key == 'preflop' else '%'
            html += (
                f'                <div style="background:rgba(0,0,0,0.2);border-radius:10px;padding:15px;">\n'
                f'                    <h4 style="color:#00ff88;margin-bottom:8px;font-size:0.95em;">{street_label}</h4>\n'
                f'                    <div style="color:#a0a0a0;font-size:0.85em;margin-bottom:8px;">'
                f'{samples} amostras &bull; M\u00e9dia: {avg:.2f}{unit} &bull; Mediana: {median:.2f}{unit}</div>\n'
            )
            dist = sd.get('distribution', [])
            for bucket in dist:
                count = bucket.get('count', 0)
                pct = bucket.get('pct', 0)
                bar_w = max(1, int(pct))
                html += (
                    f'                    <div style="display:flex;align-items:center;margin-bottom:4px;font-size:0.82em;">\n'
                    f'                        <span style="width:55px;color:#c0c0c0;">{bucket["label"]}</span>\n'
                    f'                        <div style="flex:1;background:rgba(255,255,255,0.05);border-radius:3px;height:12px;margin:0 8px;">\n'
                    f'                            <div style="width:{bar_w}%;background:#00ff88;height:100%;border-radius:3px;"></div>\n'
                    f'                        </div>\n'
                    f'                        <span style="color:#a0a0a0;width:45px;text-align:right;">{count} ({pct:.0f}%)</span>\n'
                    f'                    </div>\n'
                )
            html += '                </div>\n'
        html += '            </div>\n'

    # ── Diagnostics ──
    if diagnostics:
        html += '            <div style="margin-top:15px;">\n'
        html += '                <h4 style="color:#00ff88;margin-bottom:10px;">Diagn\u00f3stico Autom\u00e1tico</h4>\n'
        for d in diagnostics:
            if d['type'] == 'good':
                color, bg = '#00ff88', 'rgba(0,255,136,0.1)'
            elif d['type'] == 'warning':
                color, bg = '#ffa500', 'rgba(255,165,0,0.1)'
            else:
                color, bg = '#ff4444', 'rgba(255,68,68,0.1)'
            html += (
                f'                <div style="background:{bg};border:1px solid {color};'
                f'border-radius:8px;padding:10px;margin-bottom:8px;">\n'
                f'                    <strong style="color:{color};">{d["title"]}</strong>\n'
                f'                    <p style="color:#c0c0c0;font-size:0.9em;margin-top:4px;">{d["message"]}</p>\n'
                f'                </div>\n'
            )
        html += '            </div>\n'

    html += """        </div>
"""
    return html


# ── Tilt Detection & Time/Duration Performance ────────────────────────────────

def _render_tilt_analysis(data: dict) -> str:
    """Render the Tilt Detection & Performance-Timing HTML section."""

    def badge_html(severity: str, text: str = '') -> str:
        colors = {'good': '#00ff88', 'warning': '#ffa500', 'danger': '#ff4444'}
        bgs = {
            'good': 'rgba(0,255,136,0.15)',
            'warning': 'rgba(255,165,0,0.15)',
            'danger': 'rgba(255,68,68,0.15)',
        }
        color = colors.get(severity, '#a0a0a0')
        bg = bgs.get(severity, 'rgba(160,160,160,0.1)')
        label = text or {'good': 'Normal', 'warning': 'Atenção', 'danger': 'Crítico'}.get(severity, severity)
        return (
            f'<span style="background:{bg};color:{color};border:1px solid {color};'
            f'border-radius:4px;padding:2px 8px;font-size:0.8em;font-weight:600;">'
            f'{label}</span>'
        )

    def diag_html(diagnostics: list) -> str:
        if not diagnostics:
            return ''
        h = '<div style="margin-top:15px;">\n'
        h += '<h4 style="color:#00ff88;margin-bottom:10px;">Diagnóstico Automático</h4>\n'
        for d in diagnostics:
            if d['type'] == 'good':
                color, bg = '#00ff88', 'rgba(0,255,136,0.1)'
            elif d['type'] == 'warning':
                color, bg = '#ffa500', 'rgba(255,165,0,0.1)'
            else:
                color, bg = '#ff4444', 'rgba(255,68,68,0.1)'
            h += (
                f'<div style="background:{bg};border:1px solid {color};'
                f'border-radius:8px;padding:10px;margin-bottom:8px;">'
                f'<strong style="color:{color};">{d["title"]}</strong>'
                f'<p style="color:#c0c0c0;font-size:0.9em;margin-top:4px;">{d["message"]}</p>'
                f'</div>\n'
            )
        h += '</div>\n'
        return h

    tilt_count = data.get('tilt_sessions_count', 0)
    session_tilt = data.get('session_tilt', [])
    hourly = data.get('hourly', {})
    duration = data.get('duration', {})
    post_bb = data.get('post_bad_beat', {})
    recommendation = data.get('recommendation', {})
    diagnostics = data.get('diagnostics', [])

    html = """
        <div class="player-stats">
            <h2>Detecção de Tilt &amp; Performance por Horário/Duração</h2>
"""

    # ── Tilt Sessions Summary ──
    tilt_sessions_with_data = [
        s for s in session_tilt
        if s.get('total_hands', 0) >= 30
    ]
    tilt_detected_list = [s for s in session_tilt if s.get('tilt_detected')]

    if tilt_sessions_with_data:
        html += (
            f'            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin-bottom:20px;">\n'
            f'                <div class="stat-card">\n'
            f'                    <div class="stat-label">Sessões Analisadas</div>\n'
            f'                    <div class="stat-value">{len(tilt_sessions_with_data)}</div>\n'
            f'                </div>\n'
            f'                <div class="stat-card">\n'
            f'                    <div class="stat-label">Com Tilt Detectado</div>\n'
            f'                    <div class="stat-value" style="color:#ff4444;">{tilt_count}</div>\n'
            f'                </div>\n'
        )
        total_cost = sum(s.get('tilt_cost_bb', 0) for s in tilt_detected_list)
        html += (
            f'                <div class="stat-card">\n'
            f'                    <div class="stat-label">Custo Estimado do Tilt</div>\n'
            f'                    <div class="stat-value" style="color:#ffa500;">{total_cost:.0f} BB</div>\n'
            f'                </div>\n'
            f'            </div>\n'
        )

    # ── Session Tilt Table ──
    tilt_table_rows = [
        s for s in session_tilt
        if s.get('total_hands', 0) >= 30 and s.get('tilt_detected')
    ]
    if tilt_table_rows:
        html += """
            <h3 class="section-subtitle">Sessões com Tilt</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Data</th>
                        <th>Mãos</th>
                        <th>ΔVPIP</th>
                        <th>ΔPFR</th>
                        <th>ΔAF</th>
                        <th>Sinais</th>
                        <th>Custo (BB)</th>
                        <th>Badge</th>
                    </tr>
                </thead>
                <tbody>
"""
        signal_labels = {
            'vpip_spike': 'VPIP↑',
            'pfr_spike': 'PFR↑',
            'af_spike': 'AF↑',
        }
        for s in tilt_table_rows:
            sev = s.get('severity', 'warning')
            signals_str = ' '.join(
                signal_labels.get(sig, sig)
                for sig in s.get('tilt_signals', [])
            )
            vd = s.get('vpip_delta', 0)
            pd_ = s.get('pfr_delta', 0)
            ad = s.get('af_delta', 0)
            cost = s.get('tilt_cost_bb', 0)
            date_display = s.get('session_date', '')[:10]
            html += (
                f'                    <tr>\n'
                f'                        <td>{date_display}</td>\n'
                f'                        <td>{s.get("total_hands", 0)}</td>\n'
                f'                        <td style="color:#ffa500;">{vd:+.1f}pp</td>\n'
                f'                        <td style="color:#ffa500;">{pd_:+.1f}pp</td>\n'
                f'                        <td style="color:#ffa500;">{ad:+.2f}</td>\n'
                f'                        <td style="color:#ffa500;">{signals_str}</td>\n'
                f'                        <td style="color:#ff4444;">{cost:.1f}</td>\n'
                f'                        <td>{badge_html(sev, "Tilt Detected")}</td>\n'
                f'                    </tr>\n'
            )
        html += """                </tbody>
            </table>
"""

    # ── Hourly Performance Buckets ──
    hourly_buckets = hourly.get('buckets', {})
    hourly_per_hour = hourly.get('hourly', [])
    if hourly_buckets:
        html += """
            <h3 class="section-subtitle">Performance por Horário do Dia</h3>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;">
"""
        for name, _, _ in [('madrugada', 0, 6), ('manhã', 6, 12), ('tarde', 12, 18), ('noite', 18, 24)]:
            b = hourly_buckets.get(name, {'hands': 0, 'win_rate_bb100': 0.0, 'net': 0.0})
            hc = b.get('hands', 0)
            wr = b.get('win_rate_bb100', 0.0)
            net = b.get('net', 0.0)
            health = b.get('health', 'good')
            sev_color = {'good': '#00ff88', 'warning': '#ffa500', 'danger': '#ff4444'}.get(health, '#a0a0a0')
            wr_sign = '+' if wr >= 0 else ''
            net_sign = '+' if net >= 0 else ''
            html += (
                f'                <div class="stat-card">\n'
                f'                    <div class="stat-label">{name.capitalize()}</div>\n'
                f'                    <div class="stat-value" style="color:{sev_color};">'
                f'{wr_sign}{wr:.1f} bb/100</div>\n'
                f'                    <div style="color:#a0a0a0;font-size:0.85em;">'
                f'{hc} mãos &bull; {net_sign}${net:.2f}</div>\n'
                f'                    {badge_html(health)}\n'
                f'                </div>\n'
            )
        html += '            </div>\n'

    # ── Hourly Heat Map (simplified 24h grid) ──
    if hourly_per_hour:
        html += _render_hourly_heatmap(hourly_per_hour)

    # ── Duration Performance ──
    dur_buckets = duration.get('buckets', [])
    if any(b.get('hands', 0) > 0 for b in dur_buckets):
        html += """
            <h3 class="section-subtitle">Win Rate por Duração de Sessão</h3>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>Período</th>
                        <th>Mãos</th>
                        <th>Net</th>
                        <th>Win Rate (bb/100)</th>
                        <th>Saúde</th>
                    </tr>
                </thead>
                <tbody>
"""
        for b in dur_buckets:
            hc = b.get('hands', 0)
            if hc == 0:
                continue
            wr = b.get('win_rate_bb100', 0)
            net = b.get('net', 0)
            health = b.get('health', 'good')
            wr_color = '#00ff88' if wr >= 0 else '#ff4444'
            html += (
                f'                    <tr>\n'
                f'                        <td><strong>{b["label"]}</strong></td>\n'
                f'                        <td>{hc}</td>\n'
                f'                        <td class="{"positive" if net >= 0 else "negative"}">'
                f'${net:+.2f}</td>\n'
                f'                        <td style="color:{wr_color};">{wr:+.1f}</td>\n'
                f'                        <td>{badge_html(health)}</td>\n'
                f'                    </tr>\n'
            )
        html += """                </tbody>
            </table>
"""

    # ── Post-Bad-Beat Analysis ──
    bad_beats = post_bb.get('bad_beats', 0)
    if bad_beats > 0:
        post_wr = post_bb.get('post_bb_win_rate', 0.0)
        baseline_wr = post_bb.get('baseline_win_rate', 0.0)
        degradation = post_bb.get('degradation_bb100', 0.0)
        post_hands = post_bb.get('post_hands_analyzed', 0)
        deg_color = '#ff4444' if degradation < -5 else '#ffa500' if degradation < 0 else '#00ff88'
        base_color = '#00ff88' if baseline_wr >= 0 else '#ff4444'
        post_color = '#00ff88' if post_wr >= 0 else '#ff4444'
        html += f"""
            <h3 class="section-subtitle">Análise Pós-Bad-Beat</h3>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:15px;">
                <div class="stat-card">
                    <div class="stat-label">Bad Beats Detectados</div>
                    <div class="stat-value" style="color:#ffa500;">{bad_beats}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Win Rate Baseline</div>
                    <div class="stat-value" style="color:{base_color};">{baseline_wr:+.1f} bb/100</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Win Rate Pós-Bad-Beat</div>
                    <div class="stat-value" style="color:{post_color};">{post_wr:+.1f} bb/100</div>
                    <div style="color:#a0a0a0;font-size:0.8em;">{post_hands} mãos analisadas</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Degradação</div>
                    <div class="stat-value" style="color:{deg_color};">{degradation:+.1f} bb/100</div>
                </div>
            </div>
"""

    # ── Recommendation ──
    rec_text = recommendation.get('text', '')
    ideal = recommendation.get('ideal_duration')
    if rec_text:
        html += """
            <h3 class="section-subtitle">Recomendação de Duração de Sessão</h3>
            <div style="background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.3);
                        border-radius:10px;padding:15px;margin-bottom:15px;">
"""
        if ideal:
            html += (
                f'                <div style="color:#00ff88;font-weight:600;margin-bottom:8px;">'
                f'Duração Ideal: {ideal}</div>\n'
            )
        html += (
            f'                <p style="color:#c0c0c0;line-height:1.6;">{rec_text}</p>\n'
            f'            </div>\n'
        )

    # ── Diagnostics ──
    html += diag_html(diagnostics)

    html += """        </div>
"""
    return html


def _render_hourly_heatmap(hourly_data: list[dict]) -> str:
    """Render a simplified 24-hour heat-map grid of win rates.

    Each cell represents one hour (0-23).  Colour intensity scales with the
    absolute win rate; green = positive, red = negative, grey = no data.
    """
    if not hourly_data:
        return ''

    max_wr = max((abs(h.get('win_rate_bb100', 0)) for h in hourly_data), default=1.0)
    if max_wr == 0:
        max_wr = 1.0

    html = """
            <h3 class="section-subtitle">Mapa de Calor por Hora (24h)</h3>
            <div style="display:grid;grid-template-columns:repeat(12,1fr);gap:4px;margin-bottom:20px;">
"""
    for entry in hourly_data:
        hour = entry['hour']
        hc = entry['hands']
        wr = entry.get('win_rate_bb100', 0.0)

        if hc == 0:
            bg = 'rgba(255,255,255,0.05)'
            color = '#555'
            tooltip = f'{hour:02d}h: sem dados'
        else:
            intensity = min(1.0, abs(wr) / max_wr)
            if wr >= 0:
                r, g, b = 0, int(180 * intensity + 20), int(60 * intensity)
            else:
                r, g, b = int(180 * intensity + 40), 0, 0
            bg = f'rgba({r},{g},{b},0.6)'
            color = '#ffffff'
            tooltip = f'{hour:02d}h: {wr:+.1f} bb/100 ({hc} mãos)'

        html += (
            f'                <div title="{tooltip}" style="background:{bg};border-radius:4px;'
            f'padding:6px 2px;text-align:center;cursor:default;">\n'
            f'                    <div style="color:#a0a0a0;font-size:0.7em;">{hour:02d}h</div>\n'
            f'                    <div style="color:{color};font-size:0.75em;font-weight:600;">'
            f'{"—" if hc == 0 else f"{wr:+.0f}"}</div>\n'
            f'                </div>\n'
        )

    html += '            </div>\n'
    return html


# ── Hand Matrix (Preflop Range Visualization) ────────────────────────────

_RANKS = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']

# Default ideal opening ranges (% frequency) by position for overlay
_IDEAL_RANGES = {
    'UTG': {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
        'AKs', 'AQs', 'AJs', 'ATs', 'KQs',
        'AKo', 'AQo',
    },
    'MP': {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'KQs', 'KJs', 'QJs',
        'AKo', 'AQo', 'AJo', 'KQo',
    },
    'CO': {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66',
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s',
        'KQs', 'KJs', 'KTs', 'QJs', 'QTs', 'JTs', 'T9s',
        'AKo', 'AQo', 'AJo', 'ATo', 'KQo', 'KJo', 'QJo',
    },
    'BTN': {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', '44',
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        'KQs', 'KJs', 'KTs', 'K9s', 'QJs', 'QTs', 'Q9s', 'JTs', 'J9s', 'T9s', 'T8s', '98s', '87s', '76s',
        'AKo', 'AQo', 'AJo', 'ATo', 'A9o', 'KQo', 'KJo', 'KTo', 'QJo', 'QTo', 'JTo',
    },
    'SB': {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55',
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s',
        'KQs', 'KJs', 'KTs', 'K9s', 'QJs', 'QTs', 'JTs', 'J9s', 'T9s', '98s', '87s',
        'AKo', 'AQo', 'AJo', 'ATo', 'KQo', 'KJo', 'QJo',
    },
    'BB': set(),  # BB defends vs raises, no standard "open" range
}


def _render_hand_matrix_svg(matrix_data: dict, position: str = 'overall',
                             show_overlay: bool = True) -> str:
    """Generate 13x13 SVG hand matrix with color-coded cells.

    Cell color by dominant action:
    - Blue: open raise dominant
    - Yellow: call dominant
    - Red: 3-bet dominant
    Color intensity scales with play frequency.
    Overlay border shows ideal range hands for comparison.
    """
    cell_size = 36
    gap = 2
    margin = 30
    total = 13 * (cell_size + gap) - gap + margin
    width = total + margin
    height = total + margin

    ideal = _IDEAL_RANGES.get(position, set()) if show_overlay else set()

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
    svg += f'viewBox="0 0 {width} {height}" style="max-width:100%;">\n'

    # Background
    svg += f'  <rect width="{width}" height="{height}" fill="#1a1a2e" rx="8"/>\n'

    # Find max frequency for intensity scaling
    max_freq = 1.0
    for r1 in _RANKS:
        for r2 in _RANKS:
            ri = _RANKS.index(r1)
            ci = _RANKS.index(r2)
            if ri == ci:
                cat = f'{r1}{r2}'
            elif ri < ci:
                cat = f'{r1}{r2}s'  # suited: above diagonal
            else:
                cat = f'{r2}{r1}o'  # offsuit: below diagonal
            stats = matrix_data.get(cat)
            if stats and stats['frequency'] > max_freq:
                max_freq = stats['frequency']

    # Draw cells
    for row_idx, r1 in enumerate(_RANKS):
        # Row label
        y_pos = margin + row_idx * (cell_size + gap) + cell_size // 2 + 4
        svg += (f'  <text x="{margin - 6}" y="{y_pos}" fill="#a0a0a0" '
                f'font-size="10" text-anchor="end" font-family="monospace">{r1}</text>\n')

        for col_idx, r2 in enumerate(_RANKS):
            x = margin + col_idx * (cell_size + gap)
            y = margin + row_idx * (cell_size + gap)

            # Column label (top row only)
            if row_idx == 0:
                svg += (f'  <text x="{x + cell_size // 2}" y="{margin - 6}" fill="#a0a0a0" '
                        f'font-size="10" text-anchor="middle" font-family="monospace">{r2}</text>\n')

            # Determine hand category for this cell
            if row_idx == col_idx:
                cat = f'{r1}{r2}'
            elif row_idx < col_idx:
                cat = f'{r1}{r2}s'
            else:
                cat = f'{r2}{r1}o'

            stats = matrix_data.get(cat)

            if stats and stats['dealt'] > 0 and stats['played'] > 0:
                freq = stats['frequency']
                intensity = min(1.0, freq / max_freq) if max_freq > 0 else 0

                # Color by dominant action
                or_cnt = stats.get('open_raise', 0)
                call_cnt = stats.get('call', 0)
                tb_cnt = stats.get('three_bet', 0)

                max_action = max(or_cnt, call_cnt, tb_cnt)
                if max_action == 0:
                    r_c, g_c, b_c = 80, 80, 80
                elif or_cnt >= call_cnt and or_cnt >= tb_cnt:
                    # Blue for open raise
                    r_c = int(30 + 20 * (1 - intensity))
                    g_c = int(100 + 80 * intensity)
                    b_c = int(180 + 75 * intensity)
                elif tb_cnt >= or_cnt and tb_cnt >= call_cnt:
                    # Red for 3-bet
                    r_c = int(180 + 75 * intensity)
                    g_c = int(30 + 20 * (1 - intensity))
                    b_c = int(30 + 20 * (1 - intensity))
                else:
                    # Yellow for call
                    r_c = int(180 + 75 * intensity)
                    g_c = int(160 + 60 * intensity)
                    b_c = int(20 + 10 * (1 - intensity))

                alpha = 0.3 + 0.7 * intensity
                fill = f'rgba({r_c},{g_c},{b_c},{alpha:.2f})'
            else:
                fill = 'rgba(255,255,255,0.03)'

            svg += f'  <rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
            svg += f'fill="{fill}" rx="3"/>\n'

            # Ideal range overlay border
            if cat in ideal:
                svg += (f'  <rect x="{x+1}" y="{y+1}" width="{cell_size-2}" '
                        f'height="{cell_size-2}" fill="none" stroke="#00ff88" '
                        f'stroke-width="1.5" rx="3" stroke-dasharray="3,2"/>\n')

            # Text label
            font_size = 8 if len(cat) > 2 else 9
            text_color = '#e0e0e0' if stats and stats.get('dealt', 0) > 0 else '#555'
            svg += (f'  <text x="{x + cell_size // 2}" y="{y + cell_size // 2 + 3}" '
                    f'fill="{text_color}" font-size="{font_size}" text-anchor="middle" '
                    f'font-family="monospace">{cat}</text>\n')

            # Frequency subtext
            if stats and stats.get('dealt', 0) > 0 and stats.get('played', 0) > 0:
                svg += (f'  <text x="{x + cell_size // 2}" y="{y + cell_size // 2 + 13}" '
                        f'fill="#a0a0a0" font-size="6" text-anchor="middle" '
                        f'font-family="monospace">{stats["frequency"]:.0f}%</text>\n')

    svg += '</svg>\n'
    return svg


def _render_range_analysis(matrix_data: dict) -> str:
    """Render the full Preflop Range Visualization section.

    Includes:
    - Position filter tabs (Overall, UTG, MP, CO, BTN, SB, BB)
    - 13x13 SVG matrix per position
    - Legend for action colors + ideal range overlay
    - Top 10 most profitable hands table
    - Top 10 most deficit hands table
    """
    if not matrix_data or matrix_data.get('total_hands', 0) < 5:
        return ''

    overall = matrix_data.get('overall', {})
    by_position = matrix_data.get('by_position', {})
    top_profitable = matrix_data.get('top_profitable', [])
    top_deficit = matrix_data.get('top_deficit', [])

    positions = ['UTG', 'MP', 'CO', 'BTN', 'SB', 'BB']
    available_positions = [p for p in positions if p in by_position]

    html = """
        <div class="summary">
            <h2>Preflop Range Visualization</h2>
            <p style="color:#a0a0a0;margin-bottom:15px;">
                Matriz 13x13 de starting hands colorida por frequência e tipo de ação.
                Borda verde tracejada = range ideal de referência.
            </p>

            <!-- Legend -->
            <div style="display:flex;gap:15px;flex-wrap:wrap;margin-bottom:15px;align-items:center;">
                <div style="display:flex;align-items:center;gap:4px;">
                    <span style="display:inline-block;width:14px;height:14px;background:rgba(50,180,255,0.8);border-radius:3px;"></span>
                    <span style="color:#a0a0a0;font-size:0.85em;">Open Raise</span>
                </div>
                <div style="display:flex;align-items:center;gap:4px;">
                    <span style="display:inline-block;width:14px;height:14px;background:rgba(255,220,30,0.8);border-radius:3px;"></span>
                    <span style="color:#a0a0a0;font-size:0.85em;">Call</span>
                </div>
                <div style="display:flex;align-items:center;gap:4px;">
                    <span style="display:inline-block;width:14px;height:14px;background:rgba(255,50,50,0.8);border-radius:3px;"></span>
                    <span style="color:#a0a0a0;font-size:0.85em;">3-Bet</span>
                </div>
                <div style="display:flex;align-items:center;gap:4px;">
                    <span style="display:inline-block;width:14px;height:14px;border:1.5px dashed #00ff88;border-radius:3px;"></span>
                    <span style="color:#a0a0a0;font-size:0.85em;">Range Ideal</span>
                </div>
            </div>
"""

    # Position tabs
    tab_ids = ['overall'] + available_positions
    tab_labels = ['Geral'] + available_positions

    html += '            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:15px;">\n'
    for i, (tab_id, label) in enumerate(zip(tab_ids, tab_labels)):
        active = 'background:rgba(0,255,136,0.2);color:#00ff88;' if i == 0 else 'background:rgba(255,255,255,0.05);color:#a0a0a0;'
        html += (f'                <button class="range-tab" data-target="range-{tab_id}" '
                 f'style="{active}border:1px solid rgba(255,255,255,0.1);padding:6px 14px;'
                 f'border-radius:6px;cursor:pointer;font-size:0.85em;">{label}</button>\n')
    html += '            </div>\n'

    # Matrix panels
    # Overall panel
    html += '            <div class="range-panel" id="range-overall" style="display:block;">\n'
    html += '                ' + _render_hand_matrix_svg(overall, 'overall', False).replace('\n', '\n                ')
    html += '            </div>\n'

    # Per-position panels
    for pos in available_positions:
        html += f'            <div class="range-panel" id="range-{pos}" style="display:none;">\n'
        html += '                ' + _render_hand_matrix_svg(by_position.get(pos, {}), pos, True).replace('\n', '\n                ')
        html += '            </div>\n'

    # Top 10 Most Profitable Hands
    if top_profitable:
        html += """
            <h3 style="color:#00ff88;margin:20px 0 10px 0;">Top 10 Mãos Mais Lucrativas</h3>
            <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
                <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                    <th style="padding:8px;text-align:left;color:#a0a0a0;">#</th>
                    <th style="padding:8px;text-align:left;color:#a0a0a0;">Mão</th>
                    <th style="padding:8px;text-align:center;color:#a0a0a0;">Vezes</th>
                    <th style="padding:8px;text-align:center;color:#a0a0a0;">Freq%</th>
                    <th style="padding:8px;text-align:right;color:#a0a0a0;">Net ($)</th>
                    <th style="padding:8px;text-align:right;color:#a0a0a0;">Win Rate</th>
                </tr>
"""
        for i, h in enumerate(top_profitable):
            net_class = 'color:#00ff88;' if h['net'] >= 0 else 'color:#ff4444;'
            html += (f'                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">'
                     f'<td style="padding:6px 8px;">{i+1}</td>'
                     f'<td style="padding:6px 8px;font-weight:600;">{h["hand"]}</td>'
                     f'<td style="padding:6px 8px;text-align:center;">{h["dealt"]}</td>'
                     f'<td style="padding:6px 8px;text-align:center;">{h["frequency"]:.0f}%</td>'
                     f'<td style="padding:6px 8px;text-align:right;{net_class}">${h["net"]:+.2f}</td>'
                     f'<td style="padding:6px 8px;text-align:right;{net_class}">{h["win_rate"]:+.1f} bb/100</td>'
                     f'</tr>\n')
        html += '            </table>\n'

    # Top 10 Most Deficit Hands
    if top_deficit:
        html += """
            <h3 style="color:#ff4444;margin:20px 0 10px 0;">Top 10 Mãos Mais Deficitárias</h3>
            <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
                <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                    <th style="padding:8px;text-align:left;color:#a0a0a0;">#</th>
                    <th style="padding:8px;text-align:left;color:#a0a0a0;">Mão</th>
                    <th style="padding:8px;text-align:center;color:#a0a0a0;">Vezes</th>
                    <th style="padding:8px;text-align:center;color:#a0a0a0;">Freq%</th>
                    <th style="padding:8px;text-align:right;color:#a0a0a0;">Net ($)</th>
                    <th style="padding:8px;text-align:right;color:#a0a0a0;">Win Rate</th>
                </tr>
"""
        for i, h in enumerate(top_deficit):
            html += (f'                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">'
                     f'<td style="padding:6px 8px;">{i+1}</td>'
                     f'<td style="padding:6px 8px;font-weight:600;">{h["hand"]}</td>'
                     f'<td style="padding:6px 8px;text-align:center;">{h["dealt"]}</td>'
                     f'<td style="padding:6px 8px;text-align:center;">{h["frequency"]:.0f}%</td>'
                     f'<td style="padding:6px 8px;text-align:right;color:#ff4444;">${h["net"]:+.2f}</td>'
                     f'<td style="padding:6px 8px;text-align:right;color:#ff4444;">{h["win_rate"]:+.1f} bb/100</td>'
                     f'</tr>\n')
        html += '            </table>\n'

    # JavaScript for tab switching
    html += """
            <script>
            document.querySelectorAll('.range-tab').forEach(function(tab) {
                tab.addEventListener('click', function() {
                    document.querySelectorAll('.range-panel').forEach(function(p) {
                        p.style.display = 'none';
                    });
                    document.querySelectorAll('.range-tab').forEach(function(t) {
                        t.style.background = 'rgba(255,255,255,0.05)';
                        t.style.color = '#a0a0a0';
                    });
                    var target = this.getAttribute('data-target');
                    document.getElementById(target).style.display = 'block';
                    this.style.background = 'rgba(0,255,136,0.2)';
                    this.style.color = '#00ff88';
                });
            });
            </script>
        </div>
"""
    return html
