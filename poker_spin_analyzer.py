#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analisador de Spin & Gold e WSOP Express - Ciclo de Satellites
"""

import sys
import io
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Configura encoding para Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class SpinAnalyzer:
    def __init__(self, summary_folder='data/tournament-summary'):
        self.summary_folder = summary_folder
        self.spin_results = []  # Spin & Gold $2
        self.wsop_results = []  # WSOP Express $10

    def load_summary_files(self):
        """Carrega todos os arquivos de summary relevantes"""
        folder = Path(self.summary_folder)
        if not folder.exists():
            print(f"Pasta {self.summary_folder} nao encontrada!")
            return

        # Spin & Gold $2
        spin_files = list(folder.glob('*Spin*Gold*.txt'))
        print(f"Encontrados {len(spin_files)} arquivos Spin & Gold...")

        for filepath in spin_files:
            result = self.parse_summary_file(filepath, 'spin')
            if result:
                self.spin_results.append(result)

        # WSOP Express $10
        wsop_files = list(folder.glob('*SOP*Express*10*.txt'))
        print(f"Encontrados {len(wsop_files)} arquivos WSOP Express $10...")

        for filepath in wsop_files:
            result = self.parse_summary_file(filepath, 'wsop')
            if result:
                self.wsop_results.append(result)

    def parse_summary_file(self, filepath, tourney_type):
        """Parse um arquivo de summary"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            return None

        result = {
            'file': filepath.name,
            'type': tourney_type,
            'tournament_id': None,
            'tournament_name': None,
            'buy_in': 0,
            'rake': 0,
            'total_buy_in': 0,
            'prize_pool': 0,
            'players': 0,
            'position': None,
            'prize': 0,
            'prize_type': 'cash',  # 'cash' ou 'entry'
            'date': None,
            'is_winner': False
        }

        lines = content.strip().split('\n')

        for line in lines:
            # Tournament ID e nome
            if line.startswith('Tournament #'):
                match = re.match(r'Tournament #(\d+),\s*(.+?)(?:,|$)', line)
                if match:
                    result['tournament_id'] = match.group(1)
                    result['tournament_name'] = match.group(2).strip()

            # Buy-in
            if line.startswith('Buy-in:'):
                buy_in_match = re.search(r'\$([\d.]+)\+\$([\d.]+)', line)
                if buy_in_match:
                    result['buy_in'] = float(buy_in_match.group(1))
                    result['rake'] = float(buy_in_match.group(2))
                    result['total_buy_in'] = result['buy_in'] + result['rake']

            # Players
            if 'Players' in line:
                players_match = re.search(r'(\d+)\s*Players', line)
                if players_match:
                    result['players'] = int(players_match.group(1))

            # Prize Pool
            if 'Total Prize Pool:' in line:
                pool_match = re.search(r'\$([\d,.]+)', line)
                if pool_match:
                    result['prize_pool'] = float(pool_match.group(1).replace(',', ''))

            # Data
            if 'Tournament started' in line:
                date_match = re.search(r'(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})', line)
                if date_match:
                    result['date'] = datetime.strptime(date_match.group(1), '%Y/%m/%d %H:%M:%S')

            # Resultado do Hero
            if ': Hero,' in line:
                pos_match = re.search(r'(\d+)(?:st|nd|rd|th)\s*:\s*Hero,\s*(.+)', line)
                if pos_match:
                    result['position'] = int(pos_match.group(1))
                    prize_str = pos_match.group(2).strip()

                    if 'Entry' in prize_str:
                        result['prize_type'] = 'entry'
                        prize_val = re.search(r'\$([\d,.]+)', prize_str)
                        if prize_val:
                            result['prize'] = float(prize_val.group(1).replace(',', ''))
                        result['is_winner'] = True
                    elif prize_str == '$0':
                        result['prize'] = 0
                    else:
                        prize_val = re.search(r'\$([\d,.]+)', prize_str)
                        if prize_val:
                            result['prize'] = float(prize_val.group(1).replace(',', ''))

        # Spin & Gold: 1st place = winner
        if tourney_type == 'spin' and result['position'] == 1:
            result['is_winner'] = True

        return result

    def calculate_stats(self):
        """Calcula estatisticas gerais"""
        stats = {
            'spin': {
                'count': len(self.spin_results),
                'total_invested': sum(r['total_buy_in'] for r in self.spin_results),
                'total_rake': sum(r['rake'] for r in self.spin_results),
                'wins': sum(1 for r in self.spin_results if r['is_winner']),
                'tickets_won': sum(1 for r in self.spin_results if r['is_winner']),
                'ticket_value': 10,  # Cada ticket vale $10
                'results_by_position': defaultdict(int)
            },
            'wsop': {
                'count': len(self.wsop_results),
                'total_invested': sum(r['total_buy_in'] for r in self.wsop_results),
                'total_rake': sum(r['rake'] for r in self.wsop_results),
                'itm_count': sum(1 for r in self.wsop_results if r['prize'] > 0),
                'total_prizes': sum(r['prize'] for r in self.wsop_results),
                'entry_prizes': sum(r['prize'] for r in self.wsop_results if r['prize_type'] == 'entry'),
                'cash_prizes': sum(r['prize'] for r in self.wsop_results if r['prize_type'] == 'cash' and r['prize'] > 0),
                'results_by_position': defaultdict(int)
            }
        }

        # Conta posicoes
        for r in self.spin_results:
            if r['position']:
                stats['spin']['results_by_position'][r['position']] += 1

        for r in self.wsop_results:
            if r['position']:
                stats['wsop']['results_by_position'][r['position']] += 1

        # Calcula valores do ciclo
        spin = stats['spin']
        wsop = stats['wsop']

        spin['tickets_value'] = spin['tickets_won'] * spin['ticket_value']
        spin['profit_if_unused'] = spin['tickets_value'] - spin['total_invested']

        # Ciclo completo
        stats['cycle'] = {
            'real_investment': spin['total_invested'],  # So paga os Spin $2
            'tickets_generated': spin['tickets_won'],
            'tickets_used': min(spin['tickets_won'], wsop['count']),  # Tickets usados
            'extra_cash_wsop': max(0, wsop['count'] - spin['tickets_won']) * 10,  # Se jogou mais WSOP que tickets
            'total_return': wsop['total_prizes'],
            'net_profit': wsop['total_prizes'] - spin['total_invested'] - max(0, wsop['count'] - spin['tickets_won']) * 10
        }

        # Win rate
        if spin['count'] > 0:
            spin['win_rate'] = (spin['wins'] / spin['count']) * 100
        else:
            spin['win_rate'] = 0

        if wsop['count'] > 0:
            wsop['itm_rate'] = (wsop['itm_count'] / wsop['count']) * 100
        else:
            wsop['itm_rate'] = 0

        # ROI
        cycle = stats['cycle']
        total_cost = cycle['real_investment'] + cycle['extra_cash_wsop']
        if total_cost > 0:
            cycle['roi'] = ((cycle['total_return'] - total_cost) / total_cost) * 100
        else:
            cycle['roi'] = 0

        return stats

    def generate_html_report(self, output_file='spin_report.html'):
        """Gera relatorio HTML"""
        stats = self.calculate_stats()
        spin = stats['spin']
        wsop = stats['wsop']
        cycle = stats['cycle']

        # Determina se esta lucrando
        profit_class = 'positive' if cycle['net_profit'] >= 0 else 'negative'

        html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spin & Gold + WSOP Express - Analise de Ciclo</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #ffffff;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        h1 {{
            text-align: center;
            color: #ff8800;
            margin-bottom: 10px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
        }}

        .subtitle {{
            text-align: center;
            color: #a0a0a0;
            margin-bottom: 30px;
            font-size: 1.1em;
        }}

        .main-result {{
            background: linear-gradient(135deg, rgba(255, 136, 0, 0.2) 0%, rgba(255, 136, 0, 0.1) 100%);
            border: 2px solid #ff8800;
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 30px;
            text-align: center;
        }}

        .main-result h2 {{
            color: #ff8800;
            margin-bottom: 20px;
            font-size: 1.8em;
        }}

        .big-number {{
            font-size: 4em;
            font-weight: bold;
            margin: 20px 0;
        }}

        .positive {{
            color: #00ff88;
        }}

        .negative {{
            color: #ff4444;
        }}

        .neutral {{
            color: #ff8800;
        }}

        .roi-badge {{
            display: inline-block;
            background: rgba(0, 255, 136, 0.2);
            border: 1px solid #00ff88;
            border-radius: 20px;
            padding: 10px 25px;
            font-size: 1.3em;
            margin-top: 10px;
        }}

        .roi-badge.negative {{
            background: rgba(255, 68, 68, 0.2);
            border-color: #ff4444;
        }}

        .section {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}

        .section h3 {{
            color: #ff8800;
            margin-bottom: 20px;
            font-size: 1.4em;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
        }}

        .stat-card {{
            background: rgba(0, 0, 0, 0.3);
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }}

        .stat-label {{
            font-size: 0.9em;
            color: #a0a0a0;
            margin-bottom: 8px;
        }}

        .stat-value {{
            font-size: 1.8em;
            font-weight: bold;
        }}

        .flow-diagram {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
            flex-wrap: wrap;
            margin: 30px 0;
        }}

        .flow-box {{
            background: rgba(0, 0, 0, 0.3);
            border-radius: 15px;
            padding: 20px 30px;
            text-align: center;
            min-width: 200px;
        }}

        .flow-box.spin {{
            border: 2px solid #ffd700;
        }}

        .flow-box.wsop {{
            border: 2px solid #ff4444;
        }}

        .flow-box.result {{
            border: 2px solid #00ff88;
        }}

        .flow-box h4 {{
            margin-bottom: 10px;
            font-size: 1.1em;
        }}

        .flow-box .value {{
            font-size: 1.5em;
            font-weight: bold;
        }}

        .arrow {{
            font-size: 2em;
            color: #ff8800;
        }}

        .tournament-list {{
            margin-top: 20px;
        }}

        .tournament-item {{
            display: grid;
            grid-template-columns: 1fr 100px 100px 120px;
            gap: 15px;
            padding: 12px 15px;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            margin-bottom: 8px;
            align-items: center;
        }}

        .tournament-item:hover {{
            background: rgba(255, 136, 0, 0.1);
        }}

        .tournament-item.winner {{
            border-left: 3px solid #00ff88;
        }}

        .tournament-item.loser {{
            border-left: 3px solid #ff4444;
        }}

        .tournament-name {{
            font-weight: 500;
        }}

        .tournament-date {{
            color: #a0a0a0;
            font-size: 0.85em;
        }}

        .position-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: bold;
            font-size: 0.9em;
        }}

        .position-1 {{
            background: linear-gradient(135deg, #ffd700, #ffaa00);
            color: #000;
        }}

        .position-2 {{
            background: linear-gradient(135deg, #c0c0c0, #a0a0a0);
            color: #000;
        }}

        .position-3 {{
            background: linear-gradient(135deg, #cd7f32, #b87333);
            color: #000;
        }}

        .position-other {{
            background: rgba(255, 255, 255, 0.1);
            color: #a0a0a0;
        }}

        .list-header {{
            display: grid;
            grid-template-columns: 1fr 100px 100px 120px;
            gap: 15px;
            padding: 10px 15px;
            color: #a0a0a0;
            font-size: 0.85em;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            margin-bottom: 10px;
        }}

        .accordion-toggle {{
            background: rgba(255, 136, 0, 0.2);
            border: 1px solid rgba(255, 136, 0, 0.5);
            border-radius: 8px;
            padding: 12px 20px;
            margin-top: 15px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.3s ease;
            color: #ff8800;
            font-weight: bold;
        }}

        .accordion-toggle:hover {{
            background: rgba(255, 136, 0, 0.3);
        }}

        .accordion-content {{
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }}

        .accordion-content.active {{
            max-height: 5000px;
        }}

        .verdict {{
            text-align: center;
            padding: 20px;
            margin-top: 20px;
            border-radius: 15px;
            font-size: 1.3em;
        }}

        .verdict.positive {{
            background: rgba(0, 255, 136, 0.1);
            border: 2px solid #00ff88;
        }}

        .verdict.negative {{
            background: rgba(255, 68, 68, 0.1);
            border: 2px solid #ff4444;
        }}

        .footer {{
            text-align: center;
            color: #666;
            margin-top: 30px;
            padding: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Spin & Gold + WSOP Express</h1>
        <p class="subtitle">Analise do Ciclo de Satellites - $2 para $10</p>

        <div class="main-result">
            <h2>Resultado do Ciclo</h2>
            <div class="big-number {profit_class}">${cycle['net_profit']:+.2f}</div>
            <div class="roi-badge {'negative' if cycle['roi'] < 0 else ''}"">
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
            <div class="arrow">→</div>
            <div class="flow-box" style="border-color: #ffd700;">
                <h4>Tickets Ganhos</h4>
                <div class="value positive">{spin['tickets_won']} tickets</div>
                <div style="margin-top: 10px; color: #a0a0a0;">
                    Valor: ${spin['tickets_value']:.2f}
                </div>
            </div>
            <div class="arrow">→</div>
            <div class="flow-box wsop">
                <h4>WSOP Express $10</h4>
                <div class="value neutral">{wsop['count']} jogados</div>
                <div style="margin-top: 10px; color: #a0a0a0;">
                    ITM: {wsop['itm_count']}x
                </div>
            </div>
            <div class="arrow">→</div>
            <div class="flow-box result">
                <h4>Premios</h4>
                <div class="value positive">${wsop['total_prizes']:.2f}</div>
                <div style="margin-top: 10px; color: #a0a0a0;">
                    Em entries
                </div>
            </div>
        </div>

        <div class="section">
            <h3>📊 Spin & Gold $2 - Step 2</h3>
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

            <div class="accordion-toggle" onclick="toggleAccordion(this)">
                <span>Ver detalhes ({spin['count']} torneios)</span>
                <span class="arrow-icon">▼</span>
            </div>
            <div class="accordion-content">
                <div class="tournament-list">
                    <div class="list-header">
                        <span>Torneio</span>
                        <span>Posicao</span>
                        <span>Buy-in</span>
                        <span>Premio</span>
                    </div>
"""

        # Lista Spin & Gold
        for r in sorted(self.spin_results, key=lambda x: x['date'] if x['date'] else datetime.min, reverse=True):
            winner_class = 'winner' if r['is_winner'] else 'loser'
            pos = r['position'] if r['position'] else '?'
            pos_class = f'position-{pos}' if pos in [1, 2, 3] else 'position-other'
            prize_str = f"${r['prize']:.2f}" if r['prize'] > 0 else '$0'
            if r['prize_type'] == 'entry' and r['prize'] > 0:
                prize_str = f"${r['prize']:.0f} Entry"
            date_str = r['date'].strftime('%d/%m %H:%M') if r['date'] else ''

            html += f"""
                    <div class="tournament-item {winner_class}">
                        <div>
                            <div class="tournament-name">Spin & Gold $2</div>
                            <div class="tournament-date">{date_str}</div>
                        </div>
                        <div><span class="position-badge {pos_class}">{pos}º</span></div>
                        <div>${r['total_buy_in']:.2f}</div>
                        <div class="{'positive' if r['prize'] > 0 else ''}">{prize_str}</div>
                    </div>
"""

        html += """
                </div>
            </div>
        </div>
"""

        # Secao WSOP Express
        html += f"""
        <div class="section">
            <h3>🏆 WSOP Express $10 - Step 3</h3>
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

            <div class="accordion-toggle" onclick="toggleAccordion(this)">
                <span>Ver detalhes ({wsop['count']} torneios)</span>
                <span class="arrow-icon">▼</span>
            </div>
            <div class="accordion-content">
                <div class="tournament-list">
                    <div class="list-header">
                        <span>Torneio</span>
                        <span>Posicao</span>
                        <span>Buy-in</span>
                        <span>Premio</span>
                    </div>
"""

        # Lista WSOP Express
        for r in sorted(self.wsop_results, key=lambda x: x['date'] if x['date'] else datetime.min, reverse=True):
            winner_class = 'winner' if r['prize'] > 0 else 'loser'
            pos = r['position'] if r['position'] else '?'
            pos_class = f'position-{pos}' if pos in [1, 2, 3] else 'position-other'
            prize_str = f"${r['prize']:.2f}" if r['prize'] > 0 else '$0'
            if r['prize_type'] == 'entry' and r['prize'] > 0:
                prize_str = f"${r['prize']:.0f} Entry"
            date_str = r['date'].strftime('%d/%m %H:%M') if r['date'] else ''

            html += f"""
                    <div class="tournament-item {winner_class}">
                        <div>
                            <div class="tournament-name">WSOP Express $10</div>
                            <div class="tournament-date">{date_str}</div>
                        </div>
                        <div><span class="position-badge {pos_class}">{pos}º</span></div>
                        <div>${r['total_buy_in']:.2f}</div>
                        <div class="{'positive' if r['prize'] > 0 else ''}">{prize_str}</div>
                    </div>
"""

        html += """
                </div>
            </div>
        </div>
"""

        # Veredicto final
        verdict_class = 'positive' if cycle['net_profit'] >= 0 else 'negative'
        verdict_emoji = '✅' if cycle['net_profit'] >= 0 else '❌'
        verdict_text = 'VALE A PENA! Continue jogando!' if cycle['net_profit'] >= 0 else 'NO MOMENTO NAO ESTA VALENDO. Revise sua estrategia.'

        html += f"""
        <div class="section">
            <h3>📈 Resumo do Ciclo Completo</h3>
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
                {verdict_emoji} {verdict_text}
            </div>
        </div>

        <div class="footer">
            <p>Relatorio gerado automaticamente</p>
        </div>
    </div>

    <script>
    function toggleAccordion(element) {{
        element.classList.toggle('active');
        const content = element.nextElementSibling;
        content.classList.toggle('active');

        const arrow = element.querySelector('.arrow-icon');
        if (content.classList.contains('active')) {{
            arrow.textContent = '▲';
        }} else {{
            arrow.textContent = '▼';
        }}
    }}
    </script>
</body>
</html>
"""

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"\nRelatorio gerado: {output_file}")
        return output_file


def main():
    print("=" * 60)
    print("ANALISADOR SPIN & GOLD + WSOP EXPRESS")
    print("=" * 60)
    print()

    analyzer = SpinAnalyzer('data/tournament-summary')
    analyzer.load_summary_files()

    print()
    print("Gerando relatorio HTML...")
    output_file = analyzer.generate_html_report()

    print()
    print("=" * 60)
    print(f"Analise completa!")
    print(f"Relatorio salvo em: {output_file}")
    print("=" * 60)


if __name__ == '__main__':
    main()
