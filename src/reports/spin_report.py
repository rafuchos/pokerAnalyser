"""Spin & Gold cycle HTML report generator.

Produces identical output to the original poker_spin_analyzer.py,
but reads data from the SQLite database via SpinAnalyzer.
"""

from datetime import datetime

from src.analyzers.spin import SpinAnalyzer


def generate_spin_report(analyzer: SpinAnalyzer,
                         output_file: str = 'output/spin_report.html') -> str:
    """Generate the Spin & Gold cycle HTML report."""
    stats = analyzer.get_stats()
    spin = stats['spin']
    wsop = stats['wsop']
    cycle = stats['cycle']

    profit_class = 'positive' if cycle['net_profit'] >= 0 else 'negative'

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spin & Gold + WSOP Express - Analise de Ciclo</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
               background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
               min-height: 100vh; color: #ffffff; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ text-align: center; color: #ff8800; margin-bottom: 10px; font-size: 2.5em;
              text-shadow: 2px 2px 4px rgba(0,0,0,0.3); }}
        .subtitle {{ text-align: center; color: #a0a0a0; margin-bottom: 30px; font-size: 1.1em; }}
        .main-result {{ background: linear-gradient(135deg, rgba(255,136,0,0.2) 0%, rgba(255,136,0,0.1) 100%);
                        border: 2px solid #ff8800; border-radius: 20px; padding: 30px;
                        margin-bottom: 30px; text-align: center; }}
        .main-result h2 {{ color: #ff8800; margin-bottom: 20px; font-size: 1.8em; }}
        .big-number {{ font-size: 4em; font-weight: bold; margin: 20px 0; }}
        .positive {{ color: #00ff88; }}
        .negative {{ color: #ff4444; }}
        .neutral {{ color: #ff8800; }}
        .roi-badge {{ display: inline-block; background: rgba(0,255,136,0.2); border: 1px solid #00ff88;
                      border-radius: 20px; padding: 10px 25px; font-size: 1.3em; margin-top: 10px; }}
        .roi-badge.negative {{ background: rgba(255,68,68,0.2); border-color: #ff4444; }}
        .section {{ background: rgba(255,255,255,0.05); border-radius: 15px; padding: 25px;
                    margin-bottom: 20px; backdrop-filter: blur(10px);
                    border: 1px solid rgba(255,255,255,0.1); }}
        .section h3 {{ color: #ff8800; margin-bottom: 20px; font-size: 1.4em; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 15px; }}
        .stat-card {{ background: rgba(0,0,0,0.3); padding: 20px; border-radius: 12px;
                      text-align: center; }}
        .stat-label {{ font-size: 0.9em; color: #a0a0a0; margin-bottom: 8px; }}
        .stat-value {{ font-size: 1.8em; font-weight: bold; }}
        .flow-diagram {{ display: flex; align-items: center; justify-content: center; gap: 20px;
                         flex-wrap: wrap; margin: 30px 0; }}
        .flow-box {{ background: rgba(0,0,0,0.3); border-radius: 15px; padding: 20px 30px;
                     text-align: center; min-width: 200px; }}
        .flow-box.spin {{ border: 2px solid #ffd700; }}
        .flow-box.wsop {{ border: 2px solid #ff4444; }}
        .flow-box.result {{ border: 2px solid #00ff88; }}
        .flow-box h4 {{ margin-bottom: 10px; font-size: 1.1em; }}
        .flow-box .value {{ font-size: 1.5em; font-weight: bold; }}
        .arrow {{ font-size: 2em; color: #ff8800; }}
        .verdict {{ text-align: center; padding: 20px; margin-top: 20px; border-radius: 15px;
                    font-size: 1.3em; }}
        .verdict.positive {{ background: rgba(0,255,136,0.1); border: 2px solid #00ff88; }}
        .verdict.negative {{ background: rgba(255,68,68,0.1); border: 2px solid #ff4444; }}
        .footer {{ text-align: center; color: #666; margin-top: 30px; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Spin & Gold + WSOP Express</h1>
        <p class="subtitle">Analise do Ciclo de Satellites - $2 para $10</p>

        <div class="main-result">
            <h2>Resultado do Ciclo</h2>
            <div class="big-number {profit_class}">${cycle['net_profit']:+.2f}</div>
            <div class="roi-badge {'negative' if cycle['roi'] < 0 else ''}">
                ROI: {cycle['roi']:+.1f}%
            </div>
        </div>

        <div class="flow-diagram">
            <div class="flow-box spin">
                <h4>Spin & Gold $2</h4>
                <div class="value neutral">{spin['count']} jogados</div>
                <div style="margin-top: 10px; color: #a0a0a0;">
                    Investido: ${spin['total_invested']:.2f}
                </div>
            </div>
            <div class="arrow">\u2192</div>
            <div class="flow-box" style="border-color: #ffd700;">
                <h4>Tickets Ganhos</h4>
                <div class="value positive">{spin['tickets_won']} tickets</div>
                <div style="margin-top: 10px; color: #a0a0a0;">
                    Valor: ${spin['tickets_value']:.2f}
                </div>
            </div>
            <div class="arrow">\u2192</div>
            <div class="flow-box wsop">
                <h4>WSOP Express $10</h4>
                <div class="value neutral">{wsop['count']} jogados</div>
                <div style="margin-top: 10px; color: #a0a0a0;">
                    ITM: {wsop['itm_count']}x
                </div>
            </div>
            <div class="arrow">\u2192</div>
            <div class="flow-box result">
                <h4>Premios</h4>
                <div class="value positive">${wsop['total_prizes']:.2f}</div>
                <div style="margin-top: 10px; color: #a0a0a0;">
                    Em entries
                </div>
            </div>
        </div>

        <div class="section">
            <h3>Spin & Gold $2 - Step 2</h3>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Torneios Jogados</div>
                    <div class="stat-value neutral">{spin['count']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value negative">${spin['total_invested']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Rake Pago</div>
                    <div class="stat-value negative">${spin['total_rake']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Vitorias (1st)</div>
                    <div class="stat-value positive">{spin['wins']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value {'positive' if spin['win_rate'] > 16.67 else 'neutral'}">{spin['win_rate']:.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Tickets Gerados</div>
                    <div class="stat-value positive">${spin['tickets_value']:.2f}</div>
                </div>
            </div>
        </div>

        <div class="section">
            <h3>WSOP Express $10 - Step 3</h3>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Torneios Jogados</div>
                    <div class="stat-value neutral">{wsop['count']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Valor dos Tickets</div>
                    <div class="stat-value negative">${wsop['total_invested']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Rake Pago</div>
                    <div class="stat-value negative">${wsop['total_rake']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">ITM</div>
                    <div class="stat-value {'positive' if wsop['itm_count'] > 0 else 'neutral'}">{wsop['itm_count']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">ITM Rate</div>
                    <div class="stat-value neutral">{wsop['itm_rate']:.1f}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Premios</div>
                    <div class="stat-value positive">${wsop['total_prizes']:.2f}</div>
                </div>
            </div>
        </div>
"""

    verdict_class = 'positive' if cycle['net_profit'] >= 0 else 'negative'
    verdict_text = ('VALE A PENA! Continue jogando!'
                    if cycle['net_profit'] >= 0
                    else 'NO MOMENTO NAO ESTA VALENDO. Revise sua estrategia.')

    html += f"""
        <div class="section">
            <h3>Resumo do Ciclo Completo</h3>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Investimento Real</div>
                    <div class="stat-value negative">${cycle['real_investment']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Cash Extra WSOP</div>
                    <div class="stat-value {'negative' if cycle['extra_cash_wsop'] > 0 else 'neutral'}">${cycle['extra_cash_wsop']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Custo Total</div>
                    <div class="stat-value negative">${cycle['real_investment'] + cycle['extra_cash_wsop']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Retorno Total</div>
                    <div class="stat-value positive">${cycle['total_return']:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Lucro Liquido</div>
                    <div class="stat-value {profit_class}">${cycle['net_profit']:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">ROI</div>
                    <div class="stat-value {profit_class}">{cycle['roi']:+.1f}%</div>
                </div>
            </div>

            <div class="verdict {verdict_class}">
                {verdict_text}
            </div>
        </div>

        <div class="footer">
            <p>Relatorio gerado automaticamente</p>
        </div>
    </div>
</body>
</html>
"""

    from pathlib import Path
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Report generated: {output_file}")
    return output_file
