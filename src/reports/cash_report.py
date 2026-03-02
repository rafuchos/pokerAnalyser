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
        html += _render_player_stats(overall, by_position)

    # ── Postflop Analysis Section ──────────────────────────────────
    postflop_overall = postflop_stats.get('overall', {})
    if postflop_overall.get('saw_flop_hands', 0) > 0:
        html += _render_postflop_stats(
            postflop_overall,
            postflop_stats.get('by_street', {}),
            postflop_stats.get('by_week', {}),
        )

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


def _render_player_stats(overall: dict, by_position: dict) -> str:
    """Render the Player Stats HTML section."""

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

    vpip_detail = f'{overall["vpip_hands"]}/{overall["total_hands"]} m\u00e3os'
    pfr_detail = f'{overall["pfr_hands"]}/{overall["total_hands"]} m\u00e3os'
    three_bet_detail = f'{overall["three_bet_hands"]}/{overall["three_bet_opps"]} opps'
    fold_3bet_detail = f'{overall["fold_to_3bet_hands"]}/{overall["fold_to_3bet_opps"]} opps'
    ats_detail = f'{overall["ats_hands"]}/{overall["ats_opps"]} opps'

    html = f"""
        <div class="player-stats">
            <h2>Player Stats (Preflop)</h2>
            <div class="stats-grid">
                {stat_card('VPIP', overall['vpip'], overall['vpip_health'], vpip_detail)}
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
