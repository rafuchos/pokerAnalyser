import os
import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path

class PokerHandAnalyzer:
    def __init__(self, data_folder='data/cash'):
        self.data_folder = data_folder
        self.hands_by_date = defaultdict(list)
        self.daily_stats = defaultdict(lambda: {
            'hands': 0,
            'total_won': 0.0,
            'total_lost': 0.0,
            'net': 0.0,
            'biggest_win': None,
            'biggest_loss': None
        })

    def parse_hand_file(self, filepath):
        """Parse um arquivo de histórico de mãos"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Separa as mãos individuais
        hands = content.split('\n\n\n')
        parsed_hands = []

        for hand_text in hands:
            if not hand_text.strip():
                continue

            hand_info = self.parse_single_hand(hand_text)
            if hand_info:
                parsed_hands.append(hand_info)

        return parsed_hands

    def parse_single_hand(self, hand_text):
        """Analisa uma única mão"""
        lines = hand_text.strip().split('\n')
        if not lines:
            return None

        # Extrai o ID e data da mão
        header_match = re.search(r"Poker Hand #([\w\d]+):.*?\(\$(.+?)/\$(.+?)\) - (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", lines[0])
        if not header_match:
            return None

        hand_id = header_match.group(1)
        small_blind = float(header_match.group(2))
        big_blind = float(header_match.group(3))
        date_str = header_match.group(4)
        hand_date = datetime.strptime(date_str, '%Y/%m/%d %H:%M:%S')

        # Procura informações do Hero
        hero_cards = None
        hero_starting_stack = 0.0
        hero_ending_stack = 0.0
        hero_collected = 0.0

        # Pega o stack inicial do Hero
        for line in lines:
            if re.search(r'Seat \d+: Hero \(\$([\d,]+\.?\d*) in chips\)', line):
                stack_match = re.search(r'Hero \(\$([\d,]+\.?\d*) in chips\)', line)
                if stack_match:
                    hero_starting_stack = float(stack_match.group(1).replace(',', ''))
                    break

        # Pega as cartas do Hero
        for line in lines:
            if 'Dealt to Hero [' in line:
                cards_match = re.search(r'Dealt to Hero \[(.+?)\]', line)
                if cards_match:
                    hero_cards = cards_match.group(1)
                break

        # Verifica se Hero coletou alguma coisa
        for line in lines:
            if 'Hero collected' in line or 'Hero (big blind) collected' in line or 'Hero (small blind) collected' in line:
                collected_match = re.search(r'collected \$?([\d,]+\.?\d*)', line)
                if collected_match:
                    hero_collected = float(collected_match.group(1).replace(',', ''))
                    break

        # Rastreia o total investido através de todas as streets
        hero_total_invested = 0.0
        current_street_total = 0.0
        returned_to_hero = 0.0

        for line in lines:
            # Detecta mudanças de street
            if '*** FLOP ***' in line:
                hero_total_invested += current_street_total
                current_street_total = 0.0
            elif '*** TURN ***' in line:
                hero_total_invested += current_street_total
                current_street_total = 0.0
            elif '*** RIVER ***' in line:
                hero_total_invested += current_street_total
                current_street_total = 0.0

            # Uncalled bet retornado ao Hero
            if 'Uncalled bet' in line and 'returned to Hero' in line:
                uncalled_match = re.search(r'Uncalled bet \(\$?([\d,]+\.?\d*)\)', line)
                if uncalled_match:
                    returned_to_hero = float(uncalled_match.group(1).replace(',', ''))

            # Ações do Hero
            if line.startswith('Hero:'):
                # Posts blinds
                if 'posts small blind' in line:
                    current_street_total = small_blind
                elif 'posts big blind' in line:
                    current_street_total = big_blind
                # Raises - "raises X to Y" onde Y é o total investido neste street
                elif 'raises' in line:
                    raise_match = re.search(r'raises \$?([\d,]+\.?\d*) to \$?([\d,]+\.?\d*)', line)
                    if raise_match:
                        current_street_total = float(raise_match.group(2).replace(',', ''))
                # Bets, calls
                elif 'bets' in line:
                    bet_match = re.search(r'bets \$?([\d,]+\.?\d*)', line)
                    if bet_match:
                        current_street_total += float(bet_match.group(1).replace(',', ''))
                elif 'calls' in line:
                    # Verifica se é all-in
                    if 'all-in' in line:
                        call_match = re.search(r'calls \$?([\d,]+\.?\d*) and is all-in', line)
                        if call_match:
                            current_street_total += float(call_match.group(1).replace(',', ''))
                    else:
                        call_match = re.search(r'calls \$?([\d,]+\.?\d*)', line)
                        if call_match:
                            current_street_total += float(call_match.group(1).replace(',', ''))

        # Adiciona a última street
        hero_total_invested += current_street_total

        # Ajusta o investimento se teve dinheiro retornado
        hero_invested = hero_total_invested - returned_to_hero

        # Calcula o resultado líquido
        # Lucro = (o que coletou) - (o que investiu)
        net_result = hero_collected - hero_invested

        return {
            'hand_id': hand_id,
            'date': hand_date,
            'cards': hero_cards,
            'invested': hero_invested,
            'won': hero_collected,
            'net': net_result,
            'action': 'won' if net_result > 0 else ('lost' if net_result < 0 else 'break_even'),
            'blinds': f'${small_blind}/${big_blind}',
            'stack_before': hero_starting_stack
        }

    def analyze_sessions(self, all_hands):
        """Analisa e agrupa mãos em sessões (mesma lógica do session_analyzer.py)"""
        # Agora aplica a lógica de sessões
        sessions = []
        current_session = None
        session_running_total = 0.0

        for i, hand in enumerate(all_hands):
            stack_before = hand['stack_before']

            if stack_before is None:
                continue

            # Se não tem sessão atual, começa nova
            if current_session is None:
                current_session = {
                    'buy_in': stack_before,
                    'start_time': hand['date'],
                    'hands': [hand],
                    'min_stack': stack_before
                }
                session_running_total = hand['net']
            else:
                # Calcula o stack após a última mão da sessão atual
                last_hand = current_session['hands'][-1]
                last_stack_after = last_hand['stack_before'] + last_hand['net']

                # Verifica se mudou de dia
                last_date = last_hand['date'].date()
                current_date = hand['date'].date()
                day_changed = last_date != current_date

                # Nova sessão se: busted OU mudou de dia
                if last_stack_after <= 0.01 or day_changed:
                    # Finaliza sessão anterior
                    current_session['end_time'] = current_session['hands'][-1]['date']
                    final_stack = current_session['buy_in'] + session_running_total
                    if final_stack < 0:
                        final_stack = 0.0
                    current_session['cash_out'] = final_stack
                    current_session['profit'] = current_session['cash_out'] - current_session['buy_in']
                    sessions.append(current_session)

                    # Inicia nova sessão
                    current_session = {
                        'buy_in': stack_before,
                        'start_time': hand['date'],
                        'hands': [hand],
                        'min_stack': stack_before
                    }
                    session_running_total = hand['net']
                else:
                    # Continua na mesma sessão
                    current_session['hands'].append(hand)
                    session_running_total += hand['net']
                    # Atualiza o mínimo stack visto
                    stack_after = stack_before + hand['net']
                    if stack_after < current_session['min_stack']:
                        current_session['min_stack'] = stack_after

        # Finaliza última sessão
        if current_session:
            current_session['end_time'] = current_session['hands'][-1]['date']
            current_session['cash_out'] = current_session['buy_in'] + session_running_total
            if current_session['cash_out'] < 0:
                current_session['cash_out'] = 0.0
            current_session['profit'] = current_session['cash_out'] - current_session['buy_in']
            sessions.append(current_session)

        return sessions

    def analyze_all_files(self):
        """Processa todos os arquivos na pasta data"""
        data_path = Path(self.data_folder)

        if not data_path.exists():
            print(f"Pasta {self.data_folder} não existe!")
            return

        files = list(data_path.glob('*.txt'))
        print(f"Processando {len(files)} arquivos...")

        all_hands = []
        seen_hand_ids = set()
        duplicates = 0
        for filepath in files:
            print(f"  Processando {filepath.name}...")
            hands = self.parse_hand_file(filepath)

            for hand in hands:
                if hand['hand_id'] in seen_hand_ids:
                    duplicates += 1
                    continue
                seen_hand_ids.add(hand['hand_id'])
                all_hands.append(hand)
                date_key = hand['date'].strftime('%Y-%m-%d')
                self.hands_by_date[date_key].append(hand)

        if duplicates > 0:
            print(f"  >> {duplicates} maos duplicadas removidas")

        # Ordena todas as mãos por data
        all_hands.sort(key=lambda x: x['date'])

        # Analisa sessões
        all_sessions = self.analyze_sessions(all_hands)

        # Agrupa sessões por dia
        sessions_by_date = defaultdict(list)
        for session in all_sessions:
            date_key = session['start_time'].strftime('%Y-%m-%d')
            sessions_by_date[date_key].append(session)

        # Calcula estatísticas por dia
        for date_key, hands in self.hands_by_date.items():
            stats = self.daily_stats[date_key]
            stats['hands'] = len(hands)
            day_sessions = sessions_by_date.get(date_key, [])
            stats['sessions'] = day_sessions

            # Calcula buy-ins reais (dinheiro novo adicionado)
            total_buy_in = 0
            previous_cash_out = 0

            for i, session in enumerate(day_sessions):
                session_buy_in = session.get('buy_in', 0)
                session_cash_out = session.get('cash_out', 0)

                # Calcula buy-in real
                if i == 0:
                    # Primeira sessão: buy-in completo
                    real_buy_in = session_buy_in
                else:
                    # Se a sessão anterior busted (terminou com $0), próxima é rebuy completo
                    if previous_cash_out == 0:
                        real_buy_in = session_buy_in
                    else:
                        # Caso contrário, só conta a diferença se for > $5
                        difference = session_buy_in - previous_cash_out
                        if difference > 5:
                            real_buy_in = difference
                        else:
                            real_buy_in = 0

                total_buy_in += real_buy_in
                previous_cash_out = session_cash_out

            for hand in hands:
                if hand['net'] > 0:
                    stats['total_won'] += hand['net']
                else:
                    stats['total_lost'] += abs(hand['net'])

                stats['net'] += hand['net']

                # Maior ganho
                if stats['biggest_win'] is None or hand['net'] > stats['biggest_win']['net']:
                    if hand['net'] > 0:
                        stats['biggest_win'] = hand

                # Maior perda
                if stats['biggest_loss'] is None or hand['net'] < stats['biggest_loss']['net']:
                    if hand['net'] < 0:
                        stats['biggest_loss'] = hand

            stats['total_invested'] = total_buy_in

    def generate_html_report(self, output_file='poker_report.html'):
        """Gera relatório HTML"""
        html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relatório Cash 2026</title>
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
    </style>
</head>
<body>
    <div class="container">
        <h1>Relatório Cash 2026</h1>
"""

        # Resumo geral - filtra apenas 2026
        stats_2026 = {k: v for k, v in self.daily_stats.items() if k.startswith('2026-')}
        total_hands = sum(stats['hands'] for stats in stats_2026.values())
        total_net = sum(stats['net'] for stats in stats_2026.values())
        total_days = len(stats_2026)

        # Conta dias positivos e negativos
        positive_days = sum(1 for stats in stats_2026.values() if stats['net'] > 0)
        negative_days = sum(1 for stats in stats_2026.values() if stats['net'] < 0)

        hands_2026 = {k: v for k, v in self.hands_by_date.items() if k.startswith('2026-')}
        all_hands = [hand for hands in hands_2026.values() for hand in hands]
        biggest_win_overall = max(all_hands, key=lambda x: x['net']) if all_hands else None
        biggest_loss_overall = min(all_hands, key=lambda x: x['net']) if all_hands else None

        html += f"""
        <div class="summary">
            <h2>Resumo Geral</h2>
            <div class="summary-grid">
                <div class="stat-card">
                    <div class="stat-label">Total de Mãos</div>
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
                    <div class="stat-value {'positive' if total_net >= 0 else 'negative'}">${total_net:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Média por Dia</div>
                    <div class="stat-value {'positive' if total_net/total_days >= 0 else 'negative'}">${total_net/total_days:.2f}</div>
                </div>
            </div>
        </div>
"""

        # Relatórios diários - filtra apenas 2026
        sorted_dates = sorted(self.daily_stats.keys(), reverse=True)
        sorted_dates = [d for d in sorted_dates if d.startswith('2026-')]

        for date_key in sorted_dates:
            stats = self.daily_stats[date_key]
            date_obj = datetime.strptime(date_key, '%Y-%m-%d')
            date_formatted = date_obj.strftime('%d/%m/%Y (%A)')

            net_class = 'positive' if stats['net'] >= 0 else 'negative'

            # Informações de sessões
            sessions = stats.get('sessions', [])
            num_sessions = len(sessions)
            total_invested = stats.get('total_invested', 0)

            html += f"""
        <div class="daily-report">
            <div class="daily-header">
                <h3>{date_formatted}</h3>
                <span class="stat-value {net_class}">${stats['net']:.2f}</span>
            </div>

            <div class="daily-stats">
                <div class="daily-stat">
                    <div class="stat-label">Sessões</div>
                    <div class="stat-value">{num_sessions}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Mãos Jogadas</div>
                    <div class="stat-value">{stats['hands']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value">${total_invested:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Resultado Final</div>
                    <div class="stat-value {net_class}">${stats['net']:.2f}</div>
                </div>
            </div>

            <div class="notable-hands">
                <h4>Mãos Notáveis</h4>
"""

            if stats['biggest_win']:
                hand = stats['biggest_win']
                html += f"""
                <div class="hand-card win">
                    <div class="hand-details">
                        <div class="hand-info">
                            <span class="cards">Cards: {hand['cards'] or 'N/A'}</span> |
                            Blinds: {hand['blinds']}
                        </div>
                        <div class="hand-info">
                            Investido: ${hand['invested']:.2f} |
                            Ganho: ${hand['won']:.2f} |
                            <strong class="positive">Lucro: ${hand['net']:.2f}</strong>
                        </div>
                    </div>
                </div>
"""

            if stats['biggest_loss']:
                hand = stats['biggest_loss']
                html += f"""
                <div class="hand-card loss">
                    <div class="hand-details">
                        <div class="hand-info">
                            <span class="cards">Cards: {hand['cards'] or 'N/A'}</span> |
                            Blinds: {hand['blinds']}
                        </div>
                        <div class="hand-info">
                            Investido: ${hand['invested']:.2f} |
                            Ganho: ${hand['won']:.2f} |
                            <strong class="negative">Perda: ${hand['net']:.2f}</strong>
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
            <p>Relatório gerado automaticamente</p>
        </div>
    </div>
</body>
</html>
"""

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"\nRelatório gerado: {output_file}")
        return output_file

def main():
    print("=" * 60)
    print("ANALISADOR DE POKER")
    print("=" * 60)

    analyzer = PokerHandAnalyzer('data/cash')
    analyzer.analyze_all_files()

    print("\nGerando relatório HTML...")
    output_file = analyzer.generate_html_report()

    print("\n" + "=" * 60)
    print(f"Analise completa!")
    print(f"Relatorio salvo em: {output_file}")
    print("=" * 60)

if __name__ == '__main__':
    main()
