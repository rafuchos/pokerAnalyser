"""Tournament HTML report generator.

Produces a tournament report with per-tournament game stats (VPIP, PFR, AF, etc.),
chip sparklines, EV analysis chart, daily breakdowns, and tournament comparisons.
Reads data from the SQLite database via TournamentAnalyzer.
"""

from datetime import datetime

from src.analyzers.tournament import TournamentAnalyzer


def generate_tournament_report(analyzer: TournamentAnalyzer,
                               output_file: str = 'output/tournament_report.html') -> str:
    """Generate the tournament HTML report with session-focused daily layout."""
    summary = analyzer.get_summary()
    daily_reports = analyzer.get_daily_reports()
    sat_summary = analyzer.get_satellite_summary()
    global_stats = analyzer.get_tournament_game_stats()
    ev_stats = analyzer.get_ev_analysis()
    session_comparison = analyzer.get_session_comparison(daily_reports)

    total_tournaments = summary['total_tournaments']
    total_invested = summary['total_invested']
    total_won = summary['total_won']
    total_net = summary['total_net']
    total_entries = summary['total_entries']
    total_rebuys = summary['total_rebuys']
    total_rake = summary['total_rake']
    total_days = summary['total_days']
    total_hands = summary['total_hands']
    itm_count = summary['itm_count']
    itm_rate = summary['itm_rate']
    avg_buy_in = summary['avg_buy_in_per_day']
    avg_tournaments = summary['avg_tournaments_per_day']

    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relat\u00f3rio Torneios 2026</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #2e1a1a 0%, #3e1616 100%);
            color: #e0e0e0; padding: 20px; line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { text-align: center; color: #ff8800; margin-bottom: 30px; font-size: 2.5em;
             text-shadow: 0 0 10px rgba(255, 136, 0, 0.5); }
        .summary { background: rgba(255,255,255,0.05); border-radius: 15px; padding: 25px;
                    margin-bottom: 30px; backdrop-filter: blur(10px);
                    border: 1px solid rgba(255,255,255,0.1); }
        .summary h2 { color: #ff8800; margin-bottom: 15px; }
        .summary-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 15px; }
        .stat-card { background: rgba(255,136,0,0.1); padding: 15px; border-radius: 10px;
                     text-align: center; }
        .stat-label { font-size: 0.9em; color: #a0a0a0; margin-bottom: 5px; }
        .stat-value { font-size: 1.8em; font-weight: bold; }
        .stat-detail { font-size: 0.75em; color: #888; margin-top: 3px; }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .neutral { color: #ff8800; }
        .daily-report { background: rgba(255,255,255,0.05); border-radius: 15px; padding: 25px;
                        margin-bottom: 20px; backdrop-filter: blur(10px);
                        border: 1px solid rgba(255,255,255,0.1); }
        .daily-header { display: flex; justify-content: space-between; align-items: center;
                        margin-bottom: 20px; padding-bottom: 15px;
                        border-bottom: 2px solid rgba(255,136,0,0.3); }
        .daily-header h3 { color: #ff8800; font-size: 1.5em; }
        .daily-stats { display: grid; grid-template-columns: repeat(3,1fr); gap: 15px;
                       margin-bottom: 20px; }
        .daily-stat { background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;
                      text-align: center; }
        .accordion-toggle { background: rgba(255,136,0,0.2); border: 1px solid rgba(255,136,0,0.5);
            border-radius: 8px; padding: 12px 20px; margin-top: 15px; cursor: pointer;
            display: flex; justify-content: space-between; align-items: center;
            transition: all 0.3s ease; color: #ff8800; font-weight: bold; }
        .accordion-toggle:hover { background: rgba(255,136,0,0.3); border-color: #ff8800; }
        .accordion-toggle .arrow { transition: transform 0.3s ease; font-size: 1.2em; }
        .accordion-toggle.active .arrow { transform: rotate(180deg); }
        .accordion-content { max-height: 0; overflow: hidden; transition: max-height 0.3s ease; }
        .accordion-content.active { max-height: 10000px; }
        .tournament-card { background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px;
                           margin-bottom: 10px; border-left: 4px solid; }
        .tournament-card.busted { border-left-color: #ff4444; }
        .tournament-card.survived { border-left-color: #00ff88; }
        .tournament-header { font-weight: bold; color: #ff8800; margin-bottom: 8px; font-size: 1.1em; }
        .tournament-details { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
                              gap: 10px; font-size: 0.9em; }
        .detail-item { padding: 5px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px,1fr));
                      gap: 10px; margin: 10px 0; }
        .session-stat-card { background: rgba(255,136,0,0.08); padding: 8px; border-radius: 6px;
                             text-align: center; font-size: 0.85em; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
                 font-size: 0.7em; font-weight: bold; margin-top: 3px; }
        .badge-good { background: rgba(0,255,136,0.2); color: #00ff88; }
        .badge-warning { background: rgba(255,200,0,0.2); color: #ffc800; }
        .badge-danger { background: rgba(255,68,68,0.2); color: #ff4444; }
        .day-summary-stats { margin: 20px 0; padding: 15px; background: rgba(255,136,0,0.05);
                             border-radius: 10px; border: 1px solid rgba(255,136,0,0.2); }
        .day-summary-stats h4 { color: #ff8800; margin-bottom: 10px; }
        .day-stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px,1fr)); gap: 10px; }
        .comparison-section { margin: 20px 0; }
        .comparison-section h4 { color: #ff8800; margin-bottom: 10px; }
        .position-table { width: 100%; border-collapse: collapse; margin: 10px 0; }
        .position-table th, .position-table td {
            padding: 8px 12px; text-align: center;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .position-table th { color: #ff8800; background: rgba(255,136,0,0.1); }
        .player-stats { background: rgba(255,255,255,0.05); border-radius: 15px; padding: 25px;
                        margin-bottom: 30px; border: 1px solid rgba(255,255,255,0.1); }
        .player-stats h2 { color: #ff8800; margin-bottom: 15px; }
        .section-subtitle { color: #ff8800; margin: 20px 0 10px; font-size: 1.1em; }
        .notable-hands { margin: 10px 0; }
        .notable-hands h4 { color: #ff8800; margin-bottom: 5px; font-size: 0.95em; }
        .hand-card { padding: 8px 12px; border-radius: 6px; margin: 5px 0; font-size: 0.85em; }
        .hand-card.win { background: rgba(0,255,136,0.1); border-left: 3px solid #00ff88; }
        .hand-card.loss { background: rgba(255,68,68,0.1); border-left: 3px solid #ff4444; }
        .session-sparkline { display: block; }
        .footer { text-align: center; margin-top: 40px; color: #a0a0a0; font-size: 0.9em; }
        @media (max-width: 768px) {
            .summary-grid, .daily-stats, .stats-grid, .day-stats-grid { grid-template-columns: repeat(2,1fr); }
            .tournament-details { grid-template-columns: 1fr; }
        }
        @media (max-width: 480px) {
            .summary-grid, .daily-stats, .stats-grid, .day-stats-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Relat\u00f3rio Torneios 2026</h1>
"""

    net_class = 'positive' if total_net >= 0 else 'negative'
    won_class = 'positive' if total_won > 0 else 'neutral'

    html += f"""
        <div class="summary">
            <h2>Resumo Geral</h2>
            <div class="summary-grid">
                <div class="stat-card">
                    <div class="stat-label">Total de Torneios</div>
                    <div class="stat-value neutral">{total_tournaments}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value neutral">${total_invested:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Ganho</div>
                    <div class="stat-value {won_class}">${total_won:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado Final</div>
                    <div class="stat-value {net_class}">${total_net:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total de Rake</div>
                    <div class="stat-value negative">${total_rake:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total de Entries</div>
                    <div class="stat-value neutral">{total_entries}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total de Rebuys</div>
                    <div class="stat-value neutral">{total_rebuys}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Dias Jogados</div>
                    <div class="stat-value">{total_days}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">ITM</div>
                    <div class="stat-value neutral">{itm_count}/{total_tournaments} ({itm_rate:.0f}%)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">M\u00e3os de Torneio</div>
                    <div class="stat-value neutral">{total_hands}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">M\u00e9dia Buy-in/Dia</div>
                    <div class="stat-value">${avg_buy_in:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">M\u00e9dia Torneios/Dia</div>
                    <div class="stat-value">{avg_tournaments:.1f}</div>
                </div>
            </div>
        </div>
"""

    # Satellite summary
    if sat_summary:
        html += _render_satellite_summary(sat_summary)

    # Global game stats
    if global_stats and global_stats.get('total_hands', 0) > 0:
        html += _render_global_stats(global_stats)

    # EV Analysis
    if ev_stats and ev_stats.get('overall', {}).get('total_hands', 0) > 0:
        html += _render_ev_analysis(ev_stats)

    # Session comparison (across days)
    if session_comparison:
        html += _render_session_comparison(session_comparison, daily_reports)

    # Daily reports (session-focused)
    for report in daily_reports:
        html += _render_daily_report(report)

    html += """
        <div class="footer">
            <p>Relat\u00f3rio gerado automaticamente</p>
        </div>
    </div>

    <script>
    function toggleAccordion(element) {
        element.classList.toggle('active');
        const content = element.nextElementSibling;
        content.classList.toggle('active');

        const arrow = element.querySelector('.arrow');
        if (content.classList.contains('active')) {
            arrow.textContent = '\u25b2';
        } else {
            arrow.textContent = '\u25bc';
        }
    }
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


def _render_satellite_summary(sat_summary: dict) -> str:
    """Render satellite tournament summary section."""
    s_net = sat_summary.get('net', 0)
    s_net_class = 'positive' if s_net >= 0 else 'negative'
    s_invested = sat_summary.get('total_invested', 0)
    s_won = sat_summary.get('total_won', 0)
    s_rake = sat_summary.get('total_rake', 0)
    s_roi = sat_summary.get('roi', 0)

    return f"""
        <div class="summary" style="border: 1px solid rgba(255, 215, 0, 0.3);">
            <h2>Satelites & Steps</h2>
            <div class="summary-grid">
                <div class="stat-card">
                    <div class="stat-label">Total Satelites</div>
                    <div class="stat-value neutral">{sat_summary['count']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value negative">${s_invested:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Ganho</div>
                    <div class="stat-value {'positive' if s_won > 0 else 'neutral'}">${s_won:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado</div>
                    <div class="stat-value {s_net_class}">${s_net:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Rake Pago</div>
                    <div class="stat-value negative">${s_rake:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">ROI</div>
                    <div class="stat-value {s_net_class}">{s_roi:+.1f}%</div>
                </div>
            </div>
        </div>
"""


def _render_global_stats(stats: dict) -> str:
    """Render the global tournament game stats section with health badges."""

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    def stat_card(label: str, value: float, health: str, fmt: str = '{:.1f}%') -> str:
        return (
            f'<div class="stat-card">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value">{fmt.format(value)}</div>'
            f'{badge_html(health)}'
            f'</div>'
        )

    html = f"""
        <div class="player-stats">
            <h2>Tournament Stats ({stats['total_hands']} m\u00e3os)</h2>
            <div class="stats-grid">
                {stat_card('VPIP', stats['vpip'], stats['vpip_health'])}
                {stat_card('PFR', stats['pfr'], stats['pfr_health'])}
                {stat_card('3-Bet', stats['three_bet'], stats['three_bet_health'])}
                {stat_card('Fold to 3-Bet', stats['fold_to_3bet'], stats['fold_to_3bet_health'])}
                {stat_card('ATS', stats['ats'], stats['ats_health'])}
                {stat_card('AF', stats['af'], stats['af_health'], '{:.2f}')}
                {stat_card('AFq', stats['afq'], 'good', '{:.1f}%')}
                {stat_card('WTSD%', stats['wtsd'], stats['wtsd_health'])}
                {stat_card('W$SD%', stats['wsd'], stats['wsd_health'])}
                {stat_card('CBet%', stats['cbet'], stats['cbet_health'])}
                {stat_card('Fold to CBet', stats['fold_to_cbet'], stats['fold_to_cbet_health'])}
                {stat_card('Check-Raise%', stats['check_raise'], stats['check_raise_health'])}
            </div>
        </div>
"""
    return html


def _render_ev_analysis(ev_stats: dict) -> str:
    """Render the EV Analysis section with inline SVG chart."""
    overall = ev_stats['overall']
    chart_data = ev_stats.get('chart_data', [])

    luck = overall.get('luck_factor', 0)
    luck_class = 'positive' if luck >= 0 else 'negative'
    luck_label = 'acima do EV' if luck >= 0 else 'abaixo do EV'

    html = f"""
        <div class="player-stats">
            <h2>EV Analysis (Torneios)</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">All-in Hands</div>
                    <div class="stat-value">{overall['allin_hands']}</div>
                    <div class="stat-detail">{overall['total_hands']} total</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">bb/100 Real</div>
                    <div class="stat-value {'positive' if overall['bb100_real'] >= 0 else 'negative'}">{overall['bb100_real']:.2f}</div>
                    <div class="stat-detail">BB vari\u00e1vel por m\u00e3o</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">bb/100 EV</div>
                    <div class="stat-value {'positive' if overall['bb100_ev'] >= 0 else 'negative'}">{overall['bb100_ev']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Luck Factor</div>
                    <div class="stat-value {luck_class}">{luck:+.0f}</div>
                    <div class="stat-detail">{luck_label}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado Real (chips)</div>
                    <div class="stat-value {'positive' if overall['real_net'] >= 0 else 'negative'}">{overall['real_net']:+.0f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado EV (chips)</div>
                    <div class="stat-value {'positive' if overall['ev_net'] >= 0 else 'negative'}">{overall['ev_net']:+.0f}</div>
                </div>
            </div>
"""

    if chart_data and len(chart_data) >= 2:
        html += _render_ev_chart(chart_data)

    html += """
        </div>
"""
    return html


def _render_ev_chart(chart_data: list) -> str:
    """Generate inline SVG chart for EV line vs Real line (tournament chips)."""
    width = 700
    height = 300
    margin_top = 30
    margin_right = 20
    margin_bottom = 40
    margin_left = 70
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    all_values = [d['real'] for d in chart_data] + [d['ev'] for d in chart_data]
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

    real_points = ' '.join(
        f'{scale_x(d["hand"]):.1f},{scale_y(d["real"]):.1f}' for d in chart_data)
    ev_points = ' '.join(
        f'{scale_x(d["hand"]):.1f},{scale_y(d["ev"]):.1f}' for d in chart_data)

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
            f'dominant-baseline="middle">{y_val:.0f}</text>\n'
        )

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

    return f"""
            <h3 class="section-subtitle">EV Line vs Real Line</h3>
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                 style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.2);border-radius:10px;margin:15px 0;">
                {grid_html}
                {zero_line}
                <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"
                      stroke="#555" stroke-width="1"/>
                <line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"
                      stroke="#555" stroke-width="1"/>
                <polyline points="{real_points}" fill="none" stroke="#ff8800" stroke-width="2"
                          stroke-linejoin="round" opacity="0.9"/>
                <polyline points="{ev_points}" fill="none" stroke="#00aaff" stroke-width="2"
                          stroke-linejoin="round" stroke-dasharray="5,3" opacity="0.8"/>
                <rect x="{legend_x}" y="5" width="130" height="40" rx="5"
                      fill="rgba(0,0,0,0.5)"/>
                <line x1="{legend_x + 10}" y1="18" x2="{legend_x + 30}" y2="18"
                      stroke="#ff8800" stroke-width="2"/>
                <text x="{legend_x + 35}" y="18" fill="#e0e0e0" font-size="10"
                      dominant-baseline="middle">Real</text>
                <line x1="{legend_x + 10}" y1="33" x2="{legend_x + 30}" y2="33"
                      stroke="#00aaff" stroke-width="2" stroke-dasharray="5,3"/>
                <text x="{legend_x + 35}" y="33" fill="#e0e0e0" font-size="10"
                      dominant-baseline="middle">EV</text>
                <text x="{margin_left + plot_w / 2}" y="{height - 5}" text-anchor="middle"
                      fill="#888" font-size="11">M\u00e3os</text>
            </svg>
"""


def _render_tournament_stats(stats: dict) -> str:
    """Render per-tournament stats with health badges (compact)."""

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

    html = '                        <div class="stats-grid">\n'
    html += f'                            {mini_stat("VPIP", stats["vpip"], stats["vpip_health"])}\n'
    html += f'                            {mini_stat("PFR", stats["pfr"], stats["pfr_health"])}\n'
    html += f'                            {mini_stat("3-Bet", stats["three_bet"], stats["three_bet_health"])}\n'
    html += f'                            {mini_stat("AF", stats["af"], stats["af_health"], "{:.2f}")}\n'
    html += f'                            {mini_stat("WTSD%", stats["wtsd"], stats["wtsd_health"])}\n'
    html += f'                            {mini_stat("W$SD%", stats["wsd"], stats["wsd_health"])}\n'
    html += f'                            {mini_stat("CBet%", stats["cbet"], stats["cbet_health"])}\n'
    html += '                        </div>\n'
    return html


def _render_chip_sparkline(data: list[dict]) -> str:
    """Render inline SVG sparkline for chip evolution in a tournament."""
    if not data or len(data) < 2:
        return ''
    width = 300
    height = 60
    margin = 5
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    values = [d['chips'] for d in data]
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

    zero_line = ''
    if y_min < 0 < y_max:
        zy = sy(0)
        zero_line = (
            f'<line x1="{margin}" y1="{zy:.1f}" '
            f'x2="{width - margin}" y2="{zy:.1f}" '
            f'stroke="rgba(255,255,255,0.2)" stroke-width="0.5" '
            f'stroke-dasharray="2,2"/>'
        )

    return f"""                        <div style="margin:10px 0;">
                            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                                 style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.15);border-radius:6px;">
                                {zero_line}
                                <polyline points="{points}"
                                          fill="none" stroke="{line_color}" stroke-width="1.5"
                                          stroke-linejoin="round"/>
                            </svg>
                        </div>
"""


def _render_hand_card(hand: dict, is_win: bool) -> str:
    """Render a notable hand card (biggest win or loss) for tournaments."""
    cards = hand.get('hero_cards') or 'N/A'
    invested = hand.get('invested', 0) or 0
    won = hand.get('won', 0) or 0
    net = hand.get('net', 0) or 0
    blinds = f"{hand.get('blinds_sb', 0)}/{hand.get('blinds_bb', 0)}"

    css_class = 'win' if is_win else 'loss'
    result_class = 'positive' if is_win else 'negative'
    result_label = 'Ganho' if is_win else 'Perda'

    return f"""                            <div class="hand-card {css_class}">
                                Cards: {cards} | Blinds: {blinds} |
                                Investido: {invested:.0f} | Ganho: {won:.0f} |
                                <strong class="{result_class}">{result_label}: {net:+.0f}</strong>
                            </div>
"""


def _render_day_summary_stats(day_stats: dict) -> str:
    """Render day-level aggregated tournament stats (weighted average) with health badges."""
    if not day_stats or not day_stats.get('total_hands'):
        return ''

    def badge_html(health: str) -> str:
        label = {'good': 'Saud\u00e1vel', 'warning': 'Aten\u00e7\u00e3o', 'danger': 'Cr\u00edtico'}
        return f'<span class="badge badge-{health}">{label.get(health, health)}</span>'

    html = f"""
            <div class="day-summary-stats">
                <h4>Stats da Sess\u00e3o ({day_stats['total_hands']} m\u00e3os)</h4>
                <div class="stats-grid">
"""
    stats_items = [
        ('VPIP', day_stats.get('vpip', 0), day_stats.get('vpip_health', 'good'), '{:.1f}%'),
        ('PFR', day_stats.get('pfr', 0), day_stats.get('pfr_health', 'good'), '{:.1f}%'),
        ('3-Bet', day_stats.get('three_bet', 0), day_stats.get('three_bet_health', 'good'), '{:.1f}%'),
        ('AF', day_stats.get('af', 0), day_stats.get('af_health', 'good'), '{:.2f}'),
        ('WTSD%', day_stats.get('wtsd', 0), day_stats.get('wtsd_health', 'good'), '{:.1f}%'),
        ('W$SD%', day_stats.get('wsd', 0), day_stats.get('wsd_health', 'good'), '{:.1f}%'),
        ('CBet%', day_stats.get('cbet', 0), day_stats.get('cbet_health', 'good'), '{:.1f}%'),
    ]
    for label, value, health, fmt in stats_items:
        html += f"""                    <div class="session-stat-card">
                        <div class="stat-label">{label}</div>
                        <div class="stat-value">{fmt.format(value)}</div>
                        {badge_html(health)}
                    </div>
"""
    html += """                </div>
            </div>
"""
    return html


def _render_tournament_comparison(comparison: dict, tournaments: list[dict]) -> str:
    """Render comparison table between tournaments of the day."""
    if not comparison or len(tournaments) < 2:
        return ''

    html = """
            <div class="comparison-section">
                <h4>Comparativo entre Torneios</h4>
                <table class="position-table">
                    <thead>
                        <tr>
                            <th>Stat</th>
"""
    for i, td in enumerate(tournaments):
        name = td.get('name', f'T{i+1}')
        short_name = name[:20] + '...' if len(name) > 20 else name
        html += f'                            <th>{short_name}</th>\n'
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
        'net': ('Resultado', '{:+.0f}'),
    }

    for key, (label, fmt) in stat_labels.items():
        comp = comparison.get(key, {})
        best_idx = comp.get('best', -1)
        worst_idx = comp.get('worst', -1)
        html += f'                        <tr><td><strong>{label}</strong></td>\n'
        for i, td in enumerate(tournaments):
            if key == 'net':
                val = td.get('net', 0)
            else:
                val = td.get('stats', {}).get(key, 0)
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


def _render_session_sparkline(data: list[dict]) -> str:
    """Render inline SVG sparkline for aggregated session chip evolution."""
    if not data or len(data) < 2:
        return ''
    width = 400
    height = 80
    margin = 8
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    values = [d['chips'] for d in data]
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

    zero_line = ''
    if y_min < 0 < y_max:
        zy = sy(0)
        zero_line = (
            f'<line x1="{margin}" y1="{zy:.1f}" '
            f'x2="{width - margin}" y2="{zy:.1f}" '
            f'stroke="rgba(255,255,255,0.2)" stroke-width="0.5" '
            f'stroke-dasharray="2,2"/>'
        )

    return f"""
            <div style="margin:15px 0;">
                <h4 style="color:#ff8800;margin-bottom:8px;">Chips da Sess\u00e3o</h4>
                <svg class="session-sparkline" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
                     style="width:100%;max-width:{width}px;background:rgba(0,0,0,0.15);border-radius:6px;">
                    {zero_line}
                    <polyline points="{points}"
                              fill="none" stroke="{line_color}" stroke-width="2"
                              stroke-linejoin="round"/>
                </svg>
            </div>
"""


def _render_session_notable_hands(notable: dict) -> str:
    """Render session-level notable hands (biggest win/loss across all day's tournaments)."""
    bw = notable.get('biggest_win')
    bl = notable.get('biggest_loss')
    if not bw and not bl:
        return ''

    html = '            <div class="notable-hands">\n'
    html += '                <h4>M\u00e3os Not\u00e1veis da Sess\u00e3o</h4>\n'
    if bw:
        html += _render_hand_card(bw, is_win=True)
    if bl:
        html += _render_hand_card(bl, is_win=False)
    html += '            </div>\n'
    return html


def _render_session_ev_summary(day_ev: dict) -> str:
    """Render session-level EV analysis summary."""
    if not day_ev or day_ev.get('total_hands', 0) == 0:
        return ''

    luck = day_ev.get('luck_factor', 0)
    luck_class = 'positive' if luck >= 0 else 'negative'
    luck_label = 'acima do EV' if luck >= 0 else 'abaixo do EV'

    html = f"""
            <div class="day-summary-stats" style="border-color:rgba(0,170,255,0.3);">
                <h4 style="color:#00aaff;">EV da Sess\u00e3o</h4>
                <div class="stats-grid">
                    <div class="session-stat-card">
                        <div class="stat-label">All-in Hands</div>
                        <div class="stat-value">{day_ev['allin_hands']}</div>
                        <div class="stat-detail">{day_ev['total_hands']} total</div>
                    </div>
                    <div class="session-stat-card">
                        <div class="stat-label">bb/100 Real</div>
                        <div class="stat-value {'positive' if day_ev['bb100_real'] >= 0 else 'negative'}">{day_ev['bb100_real']:.2f}</div>
                    </div>
                    <div class="session-stat-card">
                        <div class="stat-label">bb/100 EV</div>
                        <div class="stat-value {'positive' if day_ev['bb100_ev'] >= 0 else 'negative'}">{day_ev['bb100_ev']:.2f}</div>
                    </div>
                    <div class="session-stat-card">
                        <div class="stat-label">Luck Factor</div>
                        <div class="stat-value {luck_class}">{luck:+.0f}</div>
                        <div class="stat-detail">{luck_label}</div>
                    </div>
                    <div class="session-stat-card">
                        <div class="stat-label">Real (chips)</div>
                        <div class="stat-value {'positive' if day_ev['real_net'] >= 0 else 'negative'}">{day_ev['real_net']:+.0f}</div>
                    </div>
                    <div class="session-stat-card">
                        <div class="stat-label">EV (chips)</div>
                        <div class="stat-value {'positive' if day_ev['ev_net'] >= 0 else 'negative'}">{day_ev['ev_net']:+.0f}</div>
                    </div>
                </div>
            </div>
"""
    return html


def _render_session_comparison(comparison: dict, daily_reports: list[dict]) -> str:
    """Render comparison between sessions across different days."""
    if not comparison or len(daily_reports) < 2:
        return ''

    html = """
        <div class="player-stats">
            <h2>Comparativo entre Sess\u00f5es</h2>
            <table class="position-table">
                <thead>
                    <tr>
                        <th>M\u00e9trica</th>
                        <th>Melhor Sess\u00e3o</th>
                        <th>Pior Sess\u00e3o</th>
                    </tr>
                </thead>
                <tbody>
"""

    metric_labels = {
        'net': ('Resultado', '${:+.2f}', '${:+.2f}'),
        'roi': ('ROI', '{:+.1f}%', '{:+.1f}%'),
        'itm': ('ITM Rate', '{:.0f}%', '{:.0f}%'),
        'hands': ('M\u00e3os', '{}', '{}'),
        'vpip': ('VPIP', '{:.1f}%', '{:.1f}%'),
        'pfr': ('PFR', '{:.1f}%', '{:.1f}%'),
        'af': ('AF', '{:.2f}', '{:.2f}'),
    }

    for key, (label, best_fmt, worst_fmt) in metric_labels.items():
        comp = comparison.get(key)
        if not comp:
            continue
        best_idx = comp['best']
        worst_idx = comp['worst']
        best_date = daily_reports[best_idx]['date']
        worst_date = daily_reports[worst_idx]['date']
        best_val = comp['best_value']
        worst_val = comp['worst_value']

        html += f"""                    <tr>
                        <td><strong>{label}</strong></td>
                        <td class="positive">{best_date} ({best_fmt.format(best_val)})</td>
                        <td class="negative">{worst_date} ({worst_fmt.format(worst_val)})</td>
                    </tr>
"""

    html += """                </tbody>
            </table>
        </div>
"""
    return html


def _render_daily_report(report: dict) -> str:
    """Render a full daily report section with session-focused layout.

    Session summary (aggregated stats, financial, sparkline, EV) is the primary view.
    Individual tournament details are inside a collapsed accordion.
    """
    date_obj = datetime.strptime(report['date'], '%Y-%m-%d')
    date_formatted = date_obj.strftime('%d/%m/%Y (%A)')
    day_net = report['net']
    day_net_class = 'positive' if day_net >= 0 else 'negative'
    session_roi = report.get('session_roi', 0)
    roi_class = 'positive' if session_roi >= 0 else 'negative'
    total_hands = report.get('total_hands', 0)

    html = f"""
        <div class="daily-report">
            <div class="daily-header">
                <h3>{date_formatted}</h3>
                <span class="stat-value {day_net_class}">${day_net:+.2f}</span>
            </div>

            <div class="daily-stats">
                <div class="daily-stat">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value">${report['total_buy_in']:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Ganho</div>
                    <div class="stat-value {'positive' if report['total_won'] > 0 else 'neutral'}">${report['total_won']:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Resultado</div>
                    <div class="stat-value {day_net_class}">${day_net:+.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">ROI</div>
                    <div class="stat-value {roi_class}">{session_roi:+.1f}%</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">ITM</div>
                    <div class="stat-value neutral">{report['itm_count']}/{report['tournament_count']} ({report['itm_rate']:.0f}%)</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">M\u00e3os</div>
                    <div class="stat-value neutral">{total_hands}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Torneios</div>
                    <div class="stat-value neutral">{report['tournament_count']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Rake</div>
                    <div class="stat-value negative">${report['total_rake']:.2f}</div>
                </div>
            </div>
"""

    # Day-level aggregated stats with health badges (primary view)
    day_stats = report.get('day_stats', {})
    if day_stats:
        html += _render_day_summary_stats(day_stats)

    # Session sparkline (aggregated chips across all tournaments)
    session_sparkline = report.get('session_sparkline', [])
    if session_sparkline and len(session_sparkline) >= 2:
        html += _render_session_sparkline(session_sparkline)

    # Session-level EV analysis
    day_ev = report.get('day_ev', {})
    if day_ev and day_ev.get('total_hands', 0) > 0:
        html += _render_session_ev_summary(day_ev)

    # Session-level notable hands
    session_notable = report.get('session_notable', {})
    if session_notable:
        html += _render_session_notable_hands(session_notable)

    # Tournament comparison (within the day)
    comparison = report.get('comparison', {})
    tournaments = report.get('tournaments', [])
    if comparison and len(tournaments) >= 2:
        html += _render_tournament_comparison(comparison, tournaments)

    # Individual tournament details in accordion (secondary, collapsed by default)
    html += f"""
            <div class="accordion-toggle" onclick="toggleAccordion(this)">
                <span>Ver detalhes dos torneios ({report['tournament_count']})</span>
                <span class="arrow">\u25bc</span>
            </div>
            <div class="accordion-content">
                <div class="tournament-list">
"""

    for t in tournaments:
        html += _render_tournament_card(t)

    html += """
                </div>
            </div>
        </div>
"""
    return html


def _render_tournament_card(t: dict) -> str:
    """Render a single tournament card with details, stats, sparkline, and notable hands."""
    prize = t.get('prize', 0) or 0
    total_cost = t.get('total_cost', 0) or 0
    net_profit = t.get('net', 0) or 0
    entries = t.get('entries', 1) or 1
    rebuys = entries - 1
    buy_in = t.get('buy_in', 0) or 0
    rake = t.get('rake', 0) or 0
    position = t.get('position')
    is_bounty = t.get('is_bounty')
    hands_count = t.get('hands_count', 0)
    tournament_name = t.get('name', 'Unknown')
    date_str = (t.get('date') or '')[11:19] or ''

    status_class = 'survived' if prize > 0 else 'busted'

    if position:
        if position == 1:
            status_text = '1st place!'
        elif position == 2:
            status_text = '2nd place!'
        elif position == 3:
            status_text = '3rd place!'
        else:
            status_text = f'{position}th place'
    else:
        status_text = 'Busted'

    net_class = 'positive' if net_profit >= 0 else 'negative'

    html = f"""
                <div class="tournament-card {status_class}">
                    <div class="tournament-header">{tournament_name}</div>
                    <div class="tournament-details">
                        <div class="detail-item">
                            <strong>Status:</strong> {status_text}
                        </div>
                        <div class="detail-item">
                            <strong>Buy-in:</strong> ${buy_in:.2f} x {entries} = <strong>${total_cost:.2f}</strong>
                        </div>
                        <div class="detail-item">
                            <strong>Pr\u00eamio:</strong> <span class="{'positive' if prize > 0 else ''}">${prize:.2f}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Lucro:</strong> <span class="{net_class}">${net_profit:+.2f}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Entries:</strong> {entries} (1 + {rebuys} rebuys)
                        </div>
                        <div class="detail-item">
                            <strong>Tipo:</strong> {'Bounty' if is_bounty else 'Vanilla'}
                        </div>
                        <div class="detail-item">
                            <strong>Rake Total:</strong> ${rake * entries:.2f}
                        </div>
                        <div class="detail-item">
                            <strong>Hor\u00e1rio:</strong> {date_str}
                        </div>
                        <div class="detail-item">
                            <strong>M\u00e3os Jogadas:</strong> {hands_count}
                        </div>
                    </div>
"""

    # Per-tournament game stats with health badges
    stats = t.get('stats', {})
    if stats and stats.get('total_hands', 0) > 0:
        html += _render_tournament_stats(stats)

    # Chip sparkline
    sparkline = t.get('sparkline', [])
    if sparkline and len(sparkline) >= 2:
        html += _render_chip_sparkline(sparkline)

    # Notable hands
    bw = t.get('biggest_win')
    bl = t.get('biggest_loss')
    if bw or bl:
        html += '                    <div class="notable-hands">\n'
        html += '                        <h4>M\u00e3os Not\u00e1veis</h4>\n'
        if bw:
            html += _render_hand_card(bw, is_win=True)
        if bl:
            html += _render_hand_card(bl, is_win=False)
        html += '                    </div>\n'

    html += """                </div>
"""
    return html
