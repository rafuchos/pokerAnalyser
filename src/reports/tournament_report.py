"""Tournament HTML report generator.

Produces identical output to the original poker_tournament_analyzer.py,
but reads data from the SQLite database via TournamentAnalyzer.
"""

from datetime import datetime

from src.analyzers.tournament import TournamentAnalyzer


def generate_tournament_report(analyzer: TournamentAnalyzer,
                               output_file: str = 'output/tournament_report.html') -> str:
    """Generate the tournament HTML report."""
    summary = analyzer.get_summary()
    daily_reports = analyzer.get_daily_reports()
    sat_summary = analyzer.get_satellite_summary()

    total_tournaments = summary['total_tournaments']
    total_invested = summary['total_invested']
    total_won = summary['total_won']
    total_net = summary['total_net']
    total_entries = summary['total_entries']
    total_rebuys = summary['total_rebuys']
    total_rake = summary['total_rake']
    total_days = summary['total_days']
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
        .footer { text-align: center; margin-top: 40px; color: #a0a0a0; font-size: 0.9em; }
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
        s_net = sat_summary.get('net', 0)
        s_net_class = 'positive' if s_net >= 0 else 'negative'
        s_invested = sat_summary.get('total_invested', 0)
        s_won = sat_summary.get('total_won', 0)
        s_rake = sat_summary.get('total_rake', 0)
        s_roi = sat_summary.get('roi', 0)

        html += f"""
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

    # Daily reports
    for report in daily_reports:
        date_obj = datetime.strptime(report['date'], '%Y-%m-%d')
        date_formatted = date_obj.strftime('%d/%m/%Y (%A)')
        day_net = report['net']
        day_net_class = 'positive' if day_net >= 0 else 'negative'

        html += f"""
        <div class="daily-report">
            <div class="daily-header">
                <h3>{date_formatted}</h3>
                <span class="stat-value {day_net_class}">${day_net:+.2f}</span>
            </div>

            <div class="daily-stats">
                <div class="daily-stat">
                    <div class="stat-label">Torneios</div>
                    <div class="stat-value neutral">{report['tournament_count']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Entries</div>
                    <div class="stat-value">{report['total_entries']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Rebuys</div>
                    <div class="stat-value">{report['rebuys']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value">${report['total_buy_in']:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Rake</div>
                    <div class="stat-value negative">${report['total_rake']:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Ganho</div>
                    <div class="stat-value {'positive' if report['total_won'] > 0 else 'neutral'}">${report['total_won']:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">ITM</div>
                    <div class="stat-value neutral">{report['itm_count']}/{report['tournament_count']} ({report['itm_rate']:.0f}%)</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Resultado Final</div>
                    <div class="stat-value {day_net_class}">${day_net:+.2f}</div>
                </div>
            </div>

            <div class="accordion-toggle" onclick="toggleAccordion(this)">
                <span>Ver detalhes dos torneios ({report['tournament_count']})</span>
                <span class="arrow">\u25bc</span>
            </div>
            <div class="accordion-content">
                <div class="tournament-list">
"""

        for t in report['tournaments']:
            prize = t.get('prize', 0) or 0
            t_buy_in = (t.get('total_buy_in', 0) or 0)
            entries = t.get('entries', 1) or 1
            total_cost = t_buy_in * entries
            net_profit = prize - total_cost
            rebuys = entries - 1
            rake = t.get('rake', 0) or 0
            bounty_val = t.get('bounty', 0) or 0
            position = t.get('position')
            is_bounty_t = t.get('is_bounty')

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

            if is_bounty_t:
                buy_in_display = f"${t_buy_in:.2f}"
            elif rake > 0:
                buy_in_display = f"${t_buy_in:.2f}"
            else:
                buy_in_display = f"${t_buy_in:.2f}"

            tournament_name = t.get('name', 'Unknown')
            date_str = (t.get('date') or '')[11:19] or ''

            html += f"""
                <div class="tournament-card {status_class}">
                    <div class="tournament-header">{tournament_name}</div>
                    <div class="tournament-details">
                        <div class="detail-item">
                            <strong>Status:</strong> {status_text}
                        </div>
                        <div class="detail-item">
                            <strong>Buy-in:</strong> ${t_buy_in:.2f} x {entries} = <strong>${total_cost:.2f}</strong>
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
                            <strong>Tipo:</strong> {'Bounty' if is_bounty_t else 'Vanilla'}
                        </div>
                        <div class="detail-item">
                            <strong>Rake Total:</strong> ${rake * entries:.2f}
                        </div>
                        <div class="detail-item">
                            <strong>Hor\u00e1rio:</strong> {date_str}
                        </div>
                    </div>
                </div>
"""

        html += """
                </div>
            </div>
        </div>
"""

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
