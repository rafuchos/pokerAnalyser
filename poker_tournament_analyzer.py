import os
import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path

class TournamentAnalyzer:
    def __init__(self, data_folder='data/tournament', summary_folder='data/tournament-summary', pokerstars_folder=None):
        self.data_folder = data_folder
        self.summary_folder = summary_folder
        self.pokerstars_folder = pokerstars_folder
        self.tournaments_by_date = defaultdict(list)
        self.daily_stats = defaultdict(lambda: {
            'tournaments': set(),
            'total_buy_in': 0.0,
            'total_won': 0.0,
            'net': 0.0,
            'tournament_count': 0,
            'rebuys': 0,
            'busted_tournaments': set()
        })
        self.tournament_details = {}
        self.summary_data = {}  # Armazena dados dos arquivos de summary por tournament_id

    def load_summary_files(self):
        """Carrega todos os arquivos de summary com informações de buy-in, posição e prêmio"""
        summary_path = Path(self.summary_folder)

        if not summary_path.exists():
            print(f"Pasta {self.summary_folder} não encontrada. Continuando sem dados de summary...")
            return

        files = list(summary_path.glob('*.txt'))
        print(f"Carregando {len(files)} arquivos de summary...")

        for filepath in files:
            summary_info = self.parse_summary_file(filepath)
            if summary_info and summary_info['tournament_id']:
                self.summary_data[summary_info['tournament_id']] = summary_info

        print(f"  OK - {len(self.summary_data)} summaries carregados")

    def parse_summary_file(self, filepath):
        """Parse um arquivo de summary de torneio"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.strip().split('\n')
        if not lines:
            return None

        summary_info = {
            'tournament_id': None,
            'tournament_name': None,
            'buy_in': 0.0,
            'rake': 0.0,
            'bounty': 0.0,
            'total_buy_in': 0.0,  # Soma de todas as partes
            'position': None,
            'prize': 0.0,
            'position_prize': 0.0,  # Premio de posicao (sem bounties)
            'total_players': 0,
            'reentries': 0,
            'is_bounty': False
        }

        # Primeira linha: Tournament #ID, Nome, Type
        # Exemplo: Tournament #252416926, $15 Bounty Hunters Holiday Special, Hold'em No Limit
        first_line_match = re.search(r'Tournament #(\d+),\s*(.+?),\s*Hold', lines[0])
        if first_line_match:
            summary_info['tournament_id'] = first_line_match.group(1)
            summary_info['tournament_name'] = first_line_match.group(2).strip()

        # Buy-in: $6.8+$1.2+$7 (bounty) ou Buy-in: $23.92+$2.08 (vanilla) ou Buy-in: $0 (freeroll)
        for line in lines:
            if line.startswith('Buy-in:'):
                # Captura tudo após "Buy-in:" e verifica se é em yen
                buy_in_match = re.search(r'Buy-in:\s*(.+)', line)
                if buy_in_match:
                    buy_in_str = buy_in_match.group(1).strip()

                    # Detecta se é yen e faz conversão (¥150 ~= $1 USD)
                    is_yen = '¥' in buy_in_str
                    yen_to_usd_rate = 150.0  # Taxa aproximada de conversão

                    # Remove símbolos monetários ($, ¥, €, etc) e espaços
                    buy_in_str = buy_in_str.replace('$', '').replace('¥', '').replace('€', '').replace(' ', '')
                    # Remove qualquer '+' no final (caso exista)
                    buy_in_str = buy_in_str.rstrip('+')
                    # Separa as partes do buy-in
                    buy_in_parts = buy_in_str.split('+')
                    # Filtra partes vazias
                    buy_in_parts = [p.strip() for p in buy_in_parts if p.strip()]

                    if not buy_in_parts:
                        summary_info['total_buy_in'] = 0.0
                    elif len(buy_in_parts) == 1:
                        # Freeroll ou valor único
                        value = float(buy_in_parts[0])
                        if is_yen:
                            value = value / yen_to_usd_rate
                        summary_info['total_buy_in'] = value
                        summary_info['buy_in'] = value
                    elif len(buy_in_parts) == 2:
                        # Torneio vanilla: prize pool + rake
                        buy_in_val = float(buy_in_parts[0])
                        rake_val = float(buy_in_parts[1])
                        if is_yen:
                            buy_in_val = buy_in_val / yen_to_usd_rate
                            rake_val = rake_val / yen_to_usd_rate
                        summary_info['buy_in'] = buy_in_val
                        summary_info['rake'] = rake_val
                        summary_info['total_buy_in'] = buy_in_val + rake_val
                    elif len(buy_in_parts) >= 3:
                        # Torneio bounty: prize pool + rake + bounty
                        buy_in_val = float(buy_in_parts[0])
                        rake_val = float(buy_in_parts[1])
                        bounty_val = float(buy_in_parts[2])
                        if is_yen:
                            buy_in_val = buy_in_val / yen_to_usd_rate
                            rake_val = rake_val / yen_to_usd_rate
                            bounty_val = bounty_val / yen_to_usd_rate
                        summary_info['buy_in'] = buy_in_val
                        summary_info['rake'] = rake_val
                        summary_info['bounty'] = bounty_val
                        summary_info['is_bounty'] = True
                        summary_info['total_buy_in'] = buy_in_val + rake_val + bounty_val

            # 6982th : Hero, $5.25 ou ¥750
            if ': Hero,' in line:
                # Detecta se tem símbolo de yen
                has_yen_prize = '¥' in line
                position_match = re.search(r'(\d+)(?:st|nd|rd|th)\s*:\s*Hero,\s*[\$¥]?([\d.,]+)', line)
                if position_match:
                    summary_info['position'] = int(position_match.group(1))
                    prize_str = position_match.group(2).replace(',', '')
                    prize_value = float(prize_str) if prize_str else 0.0
                    # Converte de yen para dólar se necessário
                    if has_yen_prize:
                        prize_value = prize_value / 150.0
                    summary_info['prize'] = prize_value

            # You made 1 re-entries and received a total of $72.78 ou ¥10800
            # ou You received a total of $5.25
            if 'You' in line and 'received' in line:
                # Procura por re-entries
                reentry_match = re.search(r'You made (\d+) re-entr(?:y|ies)', line)
                if reentry_match:
                    summary_info['reentries'] = int(reentry_match.group(1))

                # Procura pelo prize - captura apenas dígitos, vírgula e ponto
                # Detecta se tem símbolo de yen
                has_yen_in_received = '¥' in line
                prize_match = re.search(r'received a total of [\$¥]?([\d,]+\.?\d*)', line)
                if prize_match:
                    prize_str = prize_match.group(1).replace(',', '')
                    try:
                        prize_value = float(prize_str)
                        # Converte de yen para dólar se necessário
                        if has_yen_in_received:
                            prize_value = prize_value / 150.0
                        summary_info['prize'] = prize_value
                    except ValueError:
                        summary_info['prize'] = 0.0

            # 10369 Players
            if 'Players' in line:
                players_match = re.search(r'(\d+)\s+Players', line)
                if players_match:
                    summary_info['total_players'] = int(players_match.group(1))

        return summary_info

    def extract_buy_in_from_name(self, tournament_name):
        """Extrai o valor do buy-in do nome do torneio"""
        # Procura por padrões como: "15 ", "$15", "10.80", "5.40", "25 "
        # Exemplos: "15 Bounty Hunters", "Bounty Hunters 10.80", "$25 MEGA"

        # Tenta encontrar número no início
        match = re.search(r'^(\d+(?:\.\d+)?)\s', tournament_name)
        if match:
            return float(match.group(1))

        # Tenta encontrar número no final
        match = re.search(r'\s(\d+(?:\.\d+)?)\s*$', tournament_name)
        if match:
            return float(match.group(1))

        # Tenta encontrar padrões como "Main Event 54"
        match = re.search(r'\s(\d+(?:\.\d+)?)[,\s]', tournament_name)
        if match:
            return float(match.group(1))

        # Freerolls
        if 'Freeroll' in tournament_name or 'freeroll' in tournament_name:
            return 0.0

        # Spin & Gold geralmente são $2
        if 'Spin & Gold' in tournament_name or 'Step' in tournament_name:
            match = re.search(r'Step \d+ - (\d+)', tournament_name)
            if match:
                return float(match.group(1))
            return 2.0  # Default para Spin & Gold

        # Padrões de valores com $ ou sem
        match = re.search(r'\$?(\d+(?:\.\d+)?)', tournament_name)
        if match:
            return float(match.group(1))

        return 0.0  # Não conseguiu extrair

    def parse_tournament_file(self, filepath):
        """Parse um arquivo de histórico de torneio"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Procura informações de prêmio no final do arquivo
        prize_info = self.extract_prize_info(content)

        # Separa as mãos individuais
        hands = content.split('\n\n\n')
        parsed_hands = []

        for hand_text in hands:
            if not hand_text.strip():
                continue

            hand_info = self.parse_single_hand(hand_text)
            if hand_info:
                # Adiciona info de prêmio
                hand_info['prize_info'] = prize_info
                parsed_hands.append(hand_info)

        return parsed_hands

    def extract_prize_info(self, content):
        """Extrai informações de prêmio do conteúdo do arquivo"""
        prize_info = {
            'position': None,
            'prize': 0.0,
            'total_entries': 0
        }

        # Procura por linhas como: "Hero finished in 123rd place and received $45.67"
        prize_match = re.search(r'Hero finished in (\d+)(?:st|nd|rd|th) place and received \$?([\d,]+(?:\.\d+)?)', content)
        if prize_match:
            prize_info['position'] = int(prize_match.group(1))
            prize_info['prize'] = float(prize_match.group(2).replace(',', ''))

        # Procura por total de entries: "123 players"
        entries_match = re.search(r'(\d+) players?', content)
        if entries_match:
            prize_info['total_entries'] = int(entries_match.group(1))

        return prize_info

    def parse_single_hand(self, hand_text):
        """Analisa uma única mão de torneio"""
        lines = hand_text.strip().split('\n')
        if not lines:
            return None

        # Extrai informações do torneio
        # Formato: Poker Hand #TM5403642865: Tournament #249917116, #Thanks2025 $1M Flipout [Stage 1] Hold'em No Limit - Level1(10/20) - 2025/12/31 01:00:02
        header_match = re.search(
            r"Poker Hand #([\w\d]+): Tournament #([\w\d]+),\s*(.+?)\s+Hold'em.+?Level(\d+)\((\d+)/(\d+)\)\s*-\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})",
            lines[0]
        )

        if not header_match:
            return None

        hand_id = header_match.group(1)
        tournament_id = header_match.group(2)
        tournament_name = header_match.group(3).strip()
        level = int(header_match.group(4))
        small_blind = int(header_match.group(5))
        big_blind = int(header_match.group(6))
        date_str = header_match.group(7)
        hand_date = datetime.strptime(date_str, '%Y/%m/%d %H:%M:%S')

        # Procura informações do Hero
        hero_starting_stack = 0
        hero_collected = 0

        # Pega o stack inicial do Hero
        for line in lines:
            if re.search(r'Seat \d+: Hero \((\d+[\d,]*) in chips\)', line):
                stack_match = re.search(r'Hero \((\d+[\d,]*) in chips\)', line)
                if stack_match:
                    hero_starting_stack = int(stack_match.group(1).replace(',', ''))
                    break

        # Verifica se Hero coletou alguma coisa
        for line in lines:
            if 'Hero collected' in line:
                collected_match = re.search(r'Hero collected ([\d,]+)', line)
                if collected_match:
                    hero_collected += int(collected_match.group(1).replace(',', ''))

        return {
            'hand_id': hand_id,
            'tournament_id': tournament_id,
            'tournament_name': tournament_name,
            'date': hand_date,
            'level': level,
            'blinds': f'{small_blind}/{big_blind}',
            'stack': hero_starting_stack,
            'collected': hero_collected
        }

    def parse_pokerstars_file(self, filepath):
        """Parse um arquivo de hand history do PokerStars"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extrai tournament_id e buy-in do header
        header_match = re.search(
            r"Tournament #(\d+),\s*\$([\d.]+)\+\$([\d.]+)(?:\+\$([\d.]+))?\s*USD",
            content
        )
        if not header_match:
            return []

        tournament_id = 'PS' + header_match.group(1)
        buy_in_part = float(header_match.group(2))
        rake_part = 0.0
        bounty_part = 0.0

        if header_match.group(4):
            # 3 partes: prize + bounty + rake (PS formato: $7.20+$7.50+$1.80)
            bounty_part = float(header_match.group(3))
            rake_part = float(header_match.group(4))
        else:
            # 2 partes: prize + rake
            rake_part = float(header_match.group(3))

        is_bounty = bounty_part > 0
        total_buy_in_unit = buy_in_part + bounty_part + rake_part

        # Monta nome do torneio com buy-in
        if is_bounty:
            tournament_name = f"[PS] Bounty ${total_buy_in_unit:.2f}"
        else:
            tournament_name = f"[PS] MTT ${total_buy_in_unit:.2f}"

        # Conta re-entries: "gangsta221 finished the tournament\n" sem posicao
        reentries = len(re.findall(r'gangsta221 finished the tournament\s*\n', content))

        # Posicao final e premio de posicao (ITM real)
        position = None
        position_prize = 0.0
        finish_match = re.search(r'gangsta221 finished the tournament in (\d+)(?:st|nd|rd|th) place(?:\s+and received \$([\d,.]+)\.)?', content)
        if finish_match:
            position = int(finish_match.group(1))
            if finish_match.group(2):
                position_prize = float(finish_match.group(2).replace(',', ''))

        # Soma bounties ganhos
        bounty_wins = re.findall(r'gangsta221 wins \$([\d,.]+) for eliminating', content)
        total_bounties = sum(float(b.replace(',', '')) for b in bounty_wins)

        # Prize total = premio de posicao + bounties
        prize = position_prize + total_bounties

        # Armazena info de summary para o tournament_id
        self.summary_data[tournament_id] = {
            'tournament_id': tournament_id,
            'tournament_name': tournament_name,
            'buy_in': buy_in_part,
            'rake': rake_part,
            'bounty': bounty_part,
            'total_buy_in': total_buy_in_unit,
            'position': position,
            'prize': prize,
            'position_prize': position_prize,
            'total_players': 0,
            'reentries': reentries,
            'is_bounty': is_bounty
        }

        # Parse das maos individuais
        hands = content.split('\n\n\n')
        parsed_hands = []

        for hand_text in hands:
            if not hand_text.strip():
                continue

            hand_info = self.parse_pokerstars_hand(hand_text, tournament_id, tournament_name)
            if hand_info:
                parsed_hands.append(hand_info)

        return parsed_hands

    def parse_pokerstars_hand(self, hand_text, tournament_id, tournament_name):
        """Analisa uma unica mao do PokerStars"""
        lines = hand_text.strip().split('\n')
        if not lines:
            return None

        # Header: PokerStars Hand #259735656512: Tournament #3974101287, $7.20+$7.50+$1.80 USD Hold'em No Limit - Level VII (60/120) - 2026/02/15 11:46:00 BRT
        header_match = re.search(
            r"PokerStars Hand #(\d+): Tournament #(\d+),.+?Level\s*(\w+)\s*\((\d+)/(\d+)\)\s*-\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})",
            lines[0]
        )
        if not header_match:
            return None

        hand_id = 'PS' + header_match.group(1)
        level_str = header_match.group(3)
        # Converte level romano ou numerico
        try:
            level = int(level_str)
        except ValueError:
            # Romano para int simplificado
            roman_map = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10,
                        'XI':11,'XII':12,'XIII':13,'XIV':14,'XV':15,'XVI':16,'XVII':17,'XVIII':18,'XIX':19,'XX':20,
                        'XXI':21,'XXII':22,'XXIII':23,'XXIV':24,'XXV':25,'XXVI':26,'XXVII':27,'XXVIII':28,'XXIX':29,'XXX':30}
            level = roman_map.get(level_str, 1)

        small_blind = int(header_match.group(4))
        big_blind = int(header_match.group(5))
        date_str = header_match.group(6)
        hand_date = datetime.strptime(date_str, '%Y/%m/%d %H:%M:%S')

        # Stack do gangsta221
        hero_starting_stack = 0
        hero_collected = 0

        for line in lines:
            if re.search(r'Seat \d+: gangsta221 \((\d+[\d,]*) in chips', line):
                stack_match = re.search(r'gangsta221 \((\d+[\d,]*) in chips', line)
                if stack_match:
                    hero_starting_stack = int(stack_match.group(1).replace(',', ''))
                    break

        for line in lines:
            if 'gangsta221 collected' in line:
                collected_match = re.search(r'gangsta221 collected ([\d,]+)', line)
                if collected_match:
                    hero_collected += int(collected_match.group(1).replace(',', ''))

        return {
            'hand_id': hand_id,
            'tournament_id': tournament_id,
            'tournament_name': tournament_name,
            'date': hand_date,
            'level': level,
            'blinds': f'{small_blind}/{big_blind}',
            'stack': hero_starting_stack,
            'collected': hero_collected
        }

    def analyze_all_files(self):
        """Processa todos os arquivos na pasta de torneios"""
        # Primeiro carrega os dados de summary
        self.load_summary_files()
        print()

        data_path = Path(self.data_folder)

        if not data_path.exists():
            print(f"Pasta {self.data_folder} não existe!")
            return

        files = list(data_path.glob('*.txt'))
        print(f"Processando {len(files)} arquivos de torneio...")

        all_hands = []
        for filepath in files:
            print(f"  Processando {filepath.name}...")
            hands = self.parse_tournament_file(filepath)
            all_hands.extend(hands)

        # Processa arquivos PokerStars se a pasta existir
        if self.pokerstars_folder:
            ps_path = Path(self.pokerstars_folder)
            if ps_path.exists():
                # Procura em subpastas (ex: pokerstars/gangsta221/)
                ps_files = list(ps_path.glob('**/*.txt'))
                if ps_files:
                    print(f"\nProcessando {len(ps_files)} arquivos PokerStars...")
                    for filepath in ps_files:
                        print(f"  [PS] {filepath.name}...")
                        hands = self.parse_pokerstars_file(filepath)
                        all_hands.extend(hands)

        # Ordena todas as mãos por data
        all_hands.sort(key=lambda x: (x['tournament_id'], x['date']))

        # Analisa torneios
        self.analyze_tournaments(all_hands)

    def analyze_tournaments(self, all_hands):
        """Analisa os torneios identificando rebuys e resultados"""
        tournament_sessions = defaultdict(list)

        # Agrupa mãos por torneio
        for hand in all_hands:
            tournament_sessions[hand['tournament_id']].append(hand)

        # Analisa cada torneio
        for tournament_id, hands in tournament_sessions.items():
            hands.sort(key=lambda x: x['date'])

            tournament_name = hands[0]['tournament_name']
            start_date = hands[0]['date']
            date_key = start_date.strftime('%Y-%m-%d')

            # Detecta rebuys (stack chegou a 0 e depois aparece o mesmo torneio)
            rebuy_count = 0
            previous_stack = None
            max_stack = 0
            final_stack = 0

            for i, hand in enumerate(hands):
                current_stack = hand['stack']

                # Atualiza max stack
                if current_stack > max_stack:
                    max_stack = current_stack

                # Detecta rebuy: stack anterior era 0 ou muito baixo e agora subiu muito
                if previous_stack is not None:
                    if previous_stack == 0 and current_stack > 1000:
                        rebuy_count += 1

                previous_stack = current_stack

                # Último stack conhecido
                if i == len(hands) - 1:
                    final_stack = current_stack

            # Calcula total coletado no torneio
            total_collected = sum(h['collected'] for h in hands)

            # Pega informações do arquivo de summary se disponível
            summary = self.summary_data.get(tournament_id)

            if summary:
                # Usa dados do summary (mais confiáveis)
                buy_in_unit = summary['total_buy_in']  # Valor total por entry (já inclui rake e bounty)
                buy_in_breakdown = summary['buy_in']  # Apenas a parte que vai pro prize pool
                rake = summary['rake']
                bounty = summary['bounty']
                is_bounty = summary['is_bounty']
                prize = summary['prize']
                position = summary['position']
                total_entries = summary['total_players']
                # Usa re-entries do summary ao invés de tentar detectar
                reentries_from_summary = summary['reentries']
                # Total de entries = 1 (inicial) + reentries
                total_tournament_entries = 1 + reentries_from_summary
            else:
                # Fallback: extrai buy-in do nome e usa rebuy detectado
                buy_in_unit = self.extract_buy_in_from_name(tournament_name)
                buy_in_breakdown = buy_in_unit
                rake = 0.0
                bounty = 0.0
                is_bounty = False
                prize = 0.0
                position = None
                total_entries = 0
                reentries_from_summary = rebuy_count
                total_tournament_entries = 1 + rebuy_count

            # Calcula investimento total e lucro
            # Total investido = buy-in unitário (já com rake e bounty) × número de entries
            total_buy_in = buy_in_unit * total_tournament_entries
            net_profit = prize - total_buy_in

            # Detecta se e satelite
            name_lower = tournament_name.lower()
            is_satellite = any(kw in name_lower for kw in ['satellite', 'step', 'spin', 'mega to', 'sop express', 'wsop express'])

            # Armazena detalhes do torneio
            tournament_info = {
                'id': tournament_id,
                'name': tournament_name,
                'date': start_date,
                'date_key': date_key,
                'hands_played': len(hands),
                'rebuys': reentries_from_summary,  # Usa re-entries do summary ou detectado
                'entries': total_tournament_entries,  # 1 + re-entries
                'buy_in': buy_in_unit,  # Buy-in total por entry (com rake e bounty)
                'buy_in_breakdown': buy_in_breakdown,  # Apenas prize pool
                'rake': rake,
                'bounty': bounty,
                'is_bounty': is_bounty,
                'is_satellite': is_satellite,
                'total_buy_in': total_buy_in,  # buy_in × entries
                'prize': prize,
                'net_profit': net_profit,
                'position': position,
                'total_entries': total_entries,  # Total de players no torneio
                'max_stack': max_stack,
                'final_stack': final_stack,
                'total_collected': total_collected,
                'busted': final_stack == 0,
                'has_summary': summary is not None  # Indica se tem dados confiáveis
            }

            self.tournament_details[tournament_id] = tournament_info

            # Adiciona ao dia (apenas torneios normais)
            if not is_satellite:
                self.tournaments_by_date[date_key].append(tournament_info)

        # Calcula estatísticas diárias
        for date_key, tournaments in self.tournaments_by_date.items():
            stats = self.daily_stats[date_key]
            stats['tournament_count'] = len(tournaments)
            stats['tournaments'] = tournaments
            stats['rebuys'] = sum(t['rebuys'] for t in tournaments)
            stats['total_entries'] = sum(t['entries'] for t in tournaments)

            # Calcula totais monetários
            stats['total_buy_in'] = sum(t['total_buy_in'] for t in tournaments)
            stats['total_won'] = sum(t['prize'] for t in tournaments)
            stats['net'] = stats['total_won'] - stats['total_buy_in']

            # Calcula total de rake pago
            stats['total_rake'] = sum(t['rake'] * t['entries'] for t in tournaments)

            # Calcula tempo da sessão (primeiro ao último torneio)
            if tournaments:
                tournament_times = [t['date'] for t in tournaments]
                first_tournament = min(tournament_times)
                last_tournament = max(tournament_times)
                session_duration = last_tournament - first_tournament
                stats['session_duration'] = session_duration
                stats['first_tournament_time'] = first_tournament
                stats['last_tournament_time'] = last_tournament

                # Calcula média de buy-in
                stats['avg_buy_in'] = stats['total_buy_in'] / stats['tournament_count'] if stats['tournament_count'] > 0 else 0

                # Calcula % ITM (lucrou no torneio, nao conta bounty avulso)
                itm_count = sum(1 for t in tournaments if t['net_profit'] >= 0 and t['prize'] > 0)
                stats['itm_count'] = itm_count
                stats['itm_rate'] = (itm_count / stats['tournament_count'] * 100) if stats['tournament_count'] > 0 else 0
            else:
                stats['session_duration'] = None
                stats['avg_buy_in'] = 0
                stats['itm_count'] = 0
                stats['itm_rate'] = 0

    def generate_html_report(self, output_file='tournament_report.html'):
        """Gera relatório HTML para torneios"""
        html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Relatório Torneios 2026</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #2e1a1a 0%, #3e1616 100%);
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
            color: #ff8800;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 0 0 10px rgba(255, 136, 0, 0.5);
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
            color: #ff8800;
            margin-bottom: 15px;
        }

        .summary-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
        }

        .stat-card {
            background: rgba(255, 136, 0, 0.1);
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

        .neutral {
            color: #ff8800;
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
            border-bottom: 2px solid rgba(255, 136, 0, 0.3);
        }

        .daily-header h3 {
            color: #ff8800;
            font-size: 1.5em;
        }

        .daily-stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }

        .daily-stat {
            background: rgba(0, 0, 0, 0.2);
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }

        .tournament-list {
            margin-top: 20px;
        }

        .accordion-toggle {
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
        }

        .accordion-toggle:hover {
            background: rgba(255, 136, 0, 0.3);
            border-color: #ff8800;
        }

        .accordion-toggle .arrow {
            transition: transform 0.3s ease;
            font-size: 1.2em;
        }

        .accordion-toggle.active .arrow {
            transform: rotate(180deg);
        }

        .accordion-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }

        .accordion-content.active {
            max-height: 10000px;
        }

        .tournament-card {
            background: rgba(0, 0, 0, 0.3);
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 4px solid;
        }

        .tournament-card.busted {
            border-left-color: #ff4444;
        }

        .tournament-card.survived {
            border-left-color: #00ff88;
        }

        .tournament-header {
            font-weight: bold;
            color: #ff8800;
            margin-bottom: 8px;
            font-size: 1.1em;
        }

        .tournament-details {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            font-size: 0.9em;
        }

        .detail-item {
            padding: 5px;
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
        <h1>⚡ Relatório Torneios 2026 ⚡</h1>
"""

        # Resumo geral
        stats_2026 = {k: v for k, v in self.daily_stats.items() if k.startswith('2026-')}
        total_tournaments = sum(stats['tournament_count'] for stats in stats_2026.values())
        total_entries = sum(stats['total_entries'] for stats in stats_2026.values())
        total_rebuys = sum(stats['rebuys'] for stats in stats_2026.values())
        total_days = len(stats_2026)

        # Totais monetários
        total_buy_in = sum(stats['total_buy_in'] for stats in stats_2026.values())
        total_won = sum(stats['total_won'] for stats in stats_2026.values())
        total_net = sum(stats['net'] for stats in stats_2026.values())
        total_rake = sum(stats.get('total_rake', 0) for stats in stats_2026.values())

        # Calcula tempo total de sessão
        from datetime import timedelta
        total_session_time = timedelta()
        for stats in stats_2026.values():
            if stats.get('session_duration'):
                total_session_time += stats['session_duration']

        # Formata tempo total
        total_hours = int(total_session_time.total_seconds() // 3600)
        total_minutes = int((total_session_time.total_seconds() % 3600) // 60)

        # Calcula média de torneios por dia
        avg_tournaments = total_tournaments / total_days if total_days > 0 else 0
        avg_buy_in = total_buy_in / total_days if total_days > 0 else 0

        # Calcula ITM geral
        total_itm = sum(stats.get('itm_count', 0) for stats in stats_2026.values())
        total_itm_rate = (total_itm / total_tournaments * 100) if total_tournaments > 0 else 0

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
                    <div class="stat-value neutral">${total_buy_in:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Ganho</div>
                    <div class="stat-value {'positive' if total_won > 0 else 'neutral'}">${total_won:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado Final</div>
                    <div class="stat-value {'positive' if total_net >= 0 else 'negative'}">${total_net:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total de Rake</div>
                    <div class="stat-value negative">${total_rake:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Tempo Total de Sessão</div>
                    <div class="stat-value neutral">{total_hours}h {total_minutes}m</div>
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
                    <div class="stat-value neutral">{total_itm}/{total_tournaments} ({total_itm_rate:.0f}%)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Média Buy-in/Dia</div>
                    <div class="stat-value">${avg_buy_in:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Média Torneios/Dia</div>
                    <div class="stat-value">{avg_tournaments:.1f}</div>
                </div>
            </div>
        </div>
"""

        # Resumo de Satelites
        all_satellites = [t for t in self.tournament_details.values() if t.get('is_satellite', False)]
        if all_satellites:
            sat_count = len(all_satellites)
            sat_invested = sum(t['total_buy_in'] for t in all_satellites)
            sat_won = sum(t['prize'] for t in all_satellites)
            sat_net = sat_won - sat_invested
            sat_rake = sum(t['rake'] * t['entries'] for t in all_satellites)
            sat_net_class = 'positive' if sat_net >= 0 else 'negative'

            html += f"""
        <div class="summary" style="border: 1px solid rgba(255, 215, 0, 0.3);">
            <h2>Satelites & Steps</h2>
            <div class="summary-grid">
                <div class="stat-card">
                    <div class="stat-label">Total Satelites</div>
                    <div class="stat-value neutral">{sat_count}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value negative">${sat_invested:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total Ganho</div>
                    <div class="stat-value {'positive' if sat_won > 0 else 'neutral'}">${sat_won:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Resultado</div>
                    <div class="stat-value {sat_net_class}">${sat_net:+.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Rake Pago</div>
                    <div class="stat-value negative">${sat_rake:.2f}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">ROI</div>
                    <div class="stat-value {sat_net_class}">{((sat_net / sat_invested) * 100) if sat_invested > 0 else 0:+.1f}%</div>
                </div>
            </div>
        </div>
"""

        # Relatórios diários
        sorted_dates = sorted(self.daily_stats.keys(), reverse=True)
        sorted_dates = [d for d in sorted_dates if d.startswith('2026-')]

        for date_key in sorted_dates:
            stats = self.daily_stats[date_key]
            date_obj = datetime.strptime(date_key, '%Y-%m-%d')
            date_formatted = date_obj.strftime('%d/%m/%Y (%A)')

            tournaments = stats.get('tournaments', [])

            # Calcula cor do resultado do dia
            day_net = stats.get('net', 0)
            day_net_class = 'positive' if day_net >= 0 else 'negative'

            # Formata tempo de sessão do dia
            session_duration = stats.get('session_duration')
            if session_duration:
                session_hours = int(session_duration.total_seconds() // 3600)
                session_minutes = int((session_duration.total_seconds() % 3600) // 60)
                session_time_str = f"{session_hours}h {session_minutes}m"
            else:
                session_time_str = "N/A"

            html += f"""
        <div class="daily-report">
            <div class="daily-header">
                <h3>{date_formatted}</h3>
                <span class="stat-value {day_net_class}">${day_net:+.2f}</span>
            </div>

            <div class="daily-stats">
                <div class="daily-stat">
                    <div class="stat-label">Torneios</div>
                    <div class="stat-value neutral">{stats['tournament_count']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Tempo de Sessão</div>
                    <div class="stat-value neutral">{session_time_str}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Média Buy-in</div>
                    <div class="stat-value neutral">${stats.get('avg_buy_in', 0):.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Entries</div>
                    <div class="stat-value">{stats['total_entries']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Rebuys</div>
                    <div class="stat-value">{stats['rebuys']}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Investido</div>
                    <div class="stat-value">${stats['total_buy_in']:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Rake</div>
                    <div class="stat-value negative">${stats.get('total_rake', 0):.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Total Ganho</div>
                    <div class="stat-value {'positive' if stats['total_won'] > 0 else 'neutral'}">${stats['total_won']:.2f}</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">ITM</div>
                    <div class="stat-value neutral">{stats.get('itm_count', 0)}/{stats['tournament_count']} ({stats.get('itm_rate', 0):.0f}%)</div>
                </div>
                <div class="daily-stat">
                    <div class="stat-label">Resultado Final</div>
                    <div class="stat-value {day_net_class}">${day_net:+.2f}</div>
                </div>
            </div>

            <div class="accordion-toggle" onclick="toggleAccordion(this)">
                <span>Ver detalhes dos torneios ({stats['tournament_count']})</span>
                <span class="arrow">▼</span>
            </div>
            <div class="accordion-content">
                <div class="tournament-list">
"""

            for tournament in tournaments:
                status_class = 'busted' if tournament['busted'] else 'survived'

                # Define status text e posição
                if tournament['position']:
                    status_text = f'🏆 {tournament["position"]}º lugar'
                    if tournament['position'] == 1:
                        status_text = f'🥇 Campeão!'
                    elif tournament['position'] == 2:
                        status_text = f'🥈 Vice-campeão!'
                    elif tournament['position'] == 3:
                        status_text = f'🥉 3º lugar!'
                else:
                    if tournament['busted']:
                        status_text = '💀 Busted'
                    elif not tournament['has_summary']:
                        status_text = '⏳ Sem dados finais'
                    else:
                        status_text = '💀 Busted'

                # Cor do lucro
                net_class = 'positive' if tournament['net_profit'] >= 0 else 'negative'

                # Formata o buy-in com breakdown se for bounty
                if tournament.get('is_bounty', False):
                    buy_in_display = f"${tournament['buy_in']:.2f} (${tournament['buy_in_breakdown']:.2f}+${tournament['rake']:.2f}+${tournament['bounty']:.2f} bounty)"
                else:
                    if tournament.get('rake', 0) > 0:
                        buy_in_display = f"${tournament['buy_in']:.2f} (${tournament['buy_in_breakdown']:.2f}+${tournament['rake']:.2f} rake)"
                    else:
                        buy_in_display = f"${tournament['buy_in']:.2f}"

                html += f"""
                <div class="tournament-card {status_class}">
                    <div class="tournament-header">{tournament['name']}</div>
                    <div class="tournament-details">
                        <div class="detail-item">
                            <strong>Status:</strong> {status_text}
                        </div>
                        <div class="detail-item">
                            <strong>Buy-in:</strong> {buy_in_display} × {tournament['entries']} = <strong>${tournament['total_buy_in']:.2f}</strong>
                        </div>
                        <div class="detail-item">
                            <strong>Prêmio:</strong> <span class="{'positive' if tournament['prize'] > 0 else ''}">${tournament['prize']:.2f}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Lucro:</strong> <span class="{net_class}">${tournament['net_profit']:+.2f}</span>
                        </div>
                        <div class="detail-item">
                            <strong>Entries:</strong> {tournament['entries']} (1 + {tournament['rebuys']} rebuys)
                        </div>
                        <div class="detail-item">
                            <strong>Mãos:</strong> {tournament['hands_played']}
                        </div>
                        <div class="detail-item">
                            <strong>Tipo:</strong> {'Bounty' if tournament.get('is_bounty', False) else 'Vanilla'}
                        </div>
                        <div class="detail-item">
                            <strong>Rake Total:</strong> ${tournament['rake'] * tournament['entries']:.2f}
                        </div>
                        <div class="detail-item">
                            <strong>Horário:</strong> {tournament['date'].strftime('%H:%M:%S')}
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
            <p>Relatório gerado automaticamente</p>
        </div>
    </div>

    <script>
    function toggleAccordion(element) {
        element.classList.toggle('active');
        const content = element.nextElementSibling;
        content.classList.toggle('active');

        // Atualiza seta
        const arrow = element.querySelector('.arrow');
        if (content.classList.contains('active')) {
            arrow.textContent = '▲';
        } else {
            arrow.textContent = '▼';
        }
    }
    </script>
</body>
</html>
"""

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"\nRelatório gerado: {output_file}")
        return output_file

def main():
    print("=" * 60)
    print("ANALISADOR DE TORNEIOS")
    print("=" * 60)

    analyzer = TournamentAnalyzer('data/tournament', pokerstars_folder='data/pokerstars')
    analyzer.analyze_all_files()

    print("\nGerando relatório HTML...")
    output_file = analyzer.generate_html_report()

    print("\n" + "=" * 60)
    print(f"Analise completa!")
    print(f"Relatorio salvo em: {output_file}")
    print("=" * 60)

if __name__ == '__main__':
    main()
