"""Cash game HTML report generator.

Produces identical output to the original poker_cash_analyzer.py,
but reads data from the SQLite database via CashAnalyzer.
"""

from datetime import datetime

from src.analyzers.cash import CashAnalyzer


def generate_cash_report(analyzer: CashAnalyzer,
                         output_file: str = 'output/cash_report.html') -> str:
    """Generate the cash game HTML report."""
    summary = analyzer.get_summary()
    daily_reports = analyzer.get_daily_reports()
    preflop_stats = analyzer.get_preflop_stats()
    postflop_stats = analyzer.get_postflop_stats()

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
            margin-top: 20px;
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

    for report in daily_reports:
        date_obj = datetime.strptime(report['date'], '%Y-%m-%d')
        date_formatted = date_obj.strftime('%d/%m/%Y (%A)')
        net = report['net']
        net_class = 'positive' if net >= 0 else 'negative'
        num_sessions = report['num_sessions']
        total_invested = report['total_invested']

        html += f"""
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

            <div class="notable-hands">
                <h4>M\u00e3os Not\u00e1veis</h4>
"""

        bw = report.get('biggest_win')
        if bw:
            cards = bw.get('hero_cards') or 'N/A'
            invested = bw.get('invested', 0) or 0
            won = bw.get('won', 0) or 0
            bw_net = bw.get('net', 0) or 0
            blinds = f"${bw.get('blinds_sb', 0):.2f}/${bw.get('blinds_bb', 0):.2f}" if bw.get('blinds_sb') else 'N/A'
            html += f"""
                <div class="hand-card win">
                    <div class="hand-details">
                        <div class="hand-info">
                            <span class="cards">Cards: {cards}</span> |
                            Blinds: {blinds}
                        </div>
                        <div class="hand-info">
                            Investido: ${invested:.2f} |
                            Ganho: ${won:.2f} |
                            <strong class="positive">Lucro: ${bw_net:.2f}</strong>
                        </div>
                    </div>
                </div>
"""

        bl = report.get('biggest_loss')
        if bl:
            cards = bl.get('hero_cards') or 'N/A'
            invested = bl.get('invested', 0) or 0
            won = bl.get('won', 0) or 0
            bl_net = bl.get('net', 0) or 0
            blinds = f"${bl.get('blinds_sb', 0):.2f}/${bl.get('blinds_bb', 0):.2f}" if bl.get('blinds_sb') else 'N/A'
            html += f"""
                <div class="hand-card loss">
                    <div class="hand-details">
                        <div class="hand-info">
                            <span class="cards">Cards: {cards}</span> |
                            Blinds: {blinds}
                        </div>
                        <div class="hand-info">
                            Investido: ${invested:.2f} |
                            Ganho: ${won:.2f} |
                            <strong class="negative">Perda: ${bl_net:.2f}</strong>
                        </div>
                    </div>
                </div>
"""

        html += """
            </div>
        </div>
"""

    html += """
        <div class="footer">
            <p>Relat\u00f3rio gerado automaticamente</p>
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
