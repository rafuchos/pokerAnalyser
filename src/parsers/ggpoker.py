"""GGPoker hand history parser.

Extracts parsing logic from poker_cash_analyzer.py and
poker_tournament_analyzer.py into a dedicated module.
"""

import re
from datetime import datetime
from typing import Optional

from src.parsers.base import BaseParser, HandData, TournamentSummaryData


class GGPokerParser(BaseParser):
    """Parser for GGPoker hand histories (cash + tournament)."""

    platform = 'GGPoker'

    def parse_hand_file(self, filepath: str) -> list[HandData]:
        """Parse a GGPoker cash hand history file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        hands = content.split('\n\n\n')
        parsed = []

        for hand_text in hands:
            if not hand_text.strip():
                continue
            hand = self.parse_single_hand(hand_text)
            if hand:
                parsed.append(hand)

        return parsed

    def parse_single_hand(self, hand_text: str) -> Optional[HandData]:
        """Parse a single GGPoker cash hand."""
        lines = hand_text.strip().split('\n')
        if not lines:
            return None

        header_match = re.search(
            r"Poker Hand #([\w\d]+):.*?\(\$(.+?)/\$(.+?)\) - (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})",
            lines[0]
        )
        if not header_match:
            return None

        hand_id = header_match.group(1)
        small_blind = float(header_match.group(2))
        big_blind = float(header_match.group(3))
        date_str = header_match.group(4)
        hand_date = datetime.strptime(date_str, '%Y/%m/%d %H:%M:%S')

        # Extract table name
        table_match = re.search(r"Table '(.+?)'", lines[0])
        table_name = table_match.group(1) if table_match else None

        hero_cards = None
        hero_starting_stack = 0.0
        hero_collected = 0.0
        num_players = 0

        # Count players and get hero stack
        for line in lines:
            if re.match(r'Seat \d+:', line):
                num_players += 1
            if re.search(r'Seat \d+: Hero \(\$([\d,]+\.?\d*) in chips\)', line):
                stack_match = re.search(r'Hero \(\$([\d,]+\.?\d*) in chips\)', line)
                if stack_match:
                    hero_starting_stack = float(stack_match.group(1).replace(',', ''))

        # Hero cards
        for line in lines:
            if 'Dealt to Hero [' in line:
                cards_match = re.search(r'Dealt to Hero \[(.+?)\]', line)
                if cards_match:
                    hero_cards = cards_match.group(1)
                break

        # Hero collected
        for line in lines:
            if 'Hero collected' in line or 'Hero (big blind) collected' in line or 'Hero (small blind) collected' in line:
                collected_match = re.search(r'collected \$?([\d,]+\.?\d*)', line)
                if collected_match:
                    hero_collected = float(collected_match.group(1).replace(',', ''))
                    break

        # Track total invested across all streets
        hero_total_invested = 0.0
        current_street_total = 0.0
        returned_to_hero = 0.0

        for line in lines:
            if '*** FLOP ***' in line or '*** TURN ***' in line or '*** RIVER ***' in line:
                hero_total_invested += current_street_total
                current_street_total = 0.0

            if 'Uncalled bet' in line and 'returned to Hero' in line:
                uncalled_match = re.search(r'Uncalled bet \(\$?([\d,]+\.?\d*)\)', line)
                if uncalled_match:
                    returned_to_hero = float(uncalled_match.group(1).replace(',', ''))

            if line.startswith('Hero:'):
                if 'posts small blind' in line:
                    current_street_total = small_blind
                elif 'posts big blind' in line:
                    current_street_total = big_blind
                elif 'raises' in line:
                    raise_match = re.search(r'raises \$?([\d,]+\.?\d*) to \$?([\d,]+\.?\d*)', line)
                    if raise_match:
                        current_street_total = float(raise_match.group(2).replace(',', ''))
                elif 'bets' in line:
                    bet_match = re.search(r'bets \$?([\d,]+\.?\d*)', line)
                    if bet_match:
                        current_street_total += float(bet_match.group(1).replace(',', ''))
                elif 'calls' in line:
                    if 'all-in' in line:
                        call_match = re.search(r'calls \$?([\d,]+\.?\d*) and is all-in', line)
                    else:
                        call_match = re.search(r'calls \$?([\d,]+\.?\d*)', line)
                    if call_match:
                        current_street_total += float(call_match.group(1).replace(',', ''))

        hero_total_invested += current_street_total
        hero_invested = hero_total_invested - returned_to_hero
        net_result = hero_collected - hero_invested

        return HandData(
            hand_id=hand_id,
            platform='GGPoker',
            game_type='cash',
            date=hand_date,
            blinds_sb=small_blind,
            blinds_bb=big_blind,
            hero_cards=hero_cards,
            hero_position=None,
            invested=hero_invested,
            won=hero_collected,
            net=net_result,
            rake=0.0,
            table_name=table_name,
            num_players=num_players,
        )

    def parse_summary_file(self, filepath: str) -> Optional[TournamentSummaryData]:
        """Parse a GGPoker tournament summary file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        lines = content.strip().split('\n')
        if not lines:
            return None

        tournament_id = None
        tournament_name = None
        buy_in = 0.0
        rake = 0.0
        bounty = 0.0
        total_buy_in = 0.0
        position = None
        prize = 0.0
        total_players = 0
        reentries = 0
        is_bounty = False

        first_line_match = re.search(r'Tournament #(\d+),\s*(.+?),\s*Hold', lines[0])
        if first_line_match:
            tournament_id = first_line_match.group(1)
            tournament_name = first_line_match.group(2).strip()

        for line in lines:
            if line.startswith('Buy-in:'):
                buy_in_match = re.search(r'Buy-in:\s*(.+)', line)
                if buy_in_match:
                    buy_in_str = buy_in_match.group(1).strip()
                    is_yen = '\u00a5' in buy_in_str
                    yen_rate = 150.0
                    buy_in_str = buy_in_str.replace('$', '').replace('\u00a5', '').replace('\u20ac', '').replace(' ', '')
                    buy_in_str = buy_in_str.rstrip('+')
                    parts = [p.strip() for p in buy_in_str.split('+') if p.strip()]

                    if not parts:
                        total_buy_in = 0.0
                    elif len(parts) == 1:
                        val = float(parts[0])
                        if is_yen:
                            val /= yen_rate
                        total_buy_in = val
                        buy_in = val
                    elif len(parts) == 2:
                        bv, rv = float(parts[0]), float(parts[1])
                        if is_yen:
                            bv /= yen_rate
                            rv /= yen_rate
                        buy_in, rake = bv, rv
                        total_buy_in = bv + rv
                    elif len(parts) >= 3:
                        bv, rv, bov = float(parts[0]), float(parts[1]), float(parts[2])
                        if is_yen:
                            bv /= yen_rate
                            rv /= yen_rate
                            bov /= yen_rate
                        buy_in, rake, bounty = bv, rv, bov
                        is_bounty = True
                        total_buy_in = bv + rv + bov

            if ': Hero,' in line:
                has_yen = '\u00a5' in line
                pos_match = re.search(r'(\d+)(?:st|nd|rd|th)\s*:\s*Hero,\s*[\$\u00a5]?([\d.,]+)', line)
                if pos_match:
                    position = int(pos_match.group(1))
                    prize_str = pos_match.group(2).replace(',', '')
                    prize_value = float(prize_str) if prize_str else 0.0
                    if has_yen:
                        prize_value /= 150.0
                    prize = prize_value

            if 'You' in line and 'received' in line:
                re_match = re.search(r'You made (\d+) re-entr(?:y|ies)', line)
                if re_match:
                    reentries = int(re_match.group(1))
                has_yen_recv = '\u00a5' in line
                prize_match = re.search(r'received a total of [\$\u00a5]?([\d,]+\.?\d*)', line)
                if prize_match:
                    pstr = prize_match.group(1).replace(',', '')
                    try:
                        pval = float(pstr)
                        if has_yen_recv:
                            pval /= 150.0
                        prize = pval
                    except ValueError:
                        prize = 0.0

            if 'Players' in line:
                pm = re.search(r'(\d+)\s+Players', line)
                if pm:
                    total_players = int(pm.group(1))

        if not tournament_id:
            return None

        name_lower = (tournament_name or '').lower()
        is_satellite = any(
            kw in name_lower
            for kw in ['satellite', 'step', 'spin', 'mega to', 'sop express', 'wsop express']
        )

        entries = 1 + reentries

        return TournamentSummaryData(
            tournament_id=tournament_id,
            platform='GGPoker',
            name=tournament_name,
            date=None,
            buy_in=buy_in,
            rake=rake,
            bounty=bounty,
            total_buy_in=total_buy_in,
            position=position,
            prize=prize,
            bounty_won=0.0,
            total_players=total_players,
            entries=entries,
            is_bounty=is_bounty,
            is_satellite=is_satellite,
        )

    def parse_tournament_hand(self, hand_text: str) -> Optional[dict]:
        """Parse a single GGPoker tournament hand (returns raw dict for session analysis)."""
        lines = hand_text.strip().split('\n')
        if not lines:
            return None

        header_match = re.search(
            r"Poker Hand #([\w\d]+): Tournament #([\w\d]+),\s*(.+?)\s+Hold'em.+?"
            r"Level(\d+)\((\d+)/(\d+)\)\s*-\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})",
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

        hero_starting_stack = 0
        hero_collected = 0

        for line in lines:
            if re.search(r'Seat \d+: Hero \((\d+[\d,]*) in chips\)', line):
                stack_match = re.search(r'Hero \((\d+[\d,]*) in chips\)', line)
                if stack_match:
                    hero_starting_stack = int(stack_match.group(1).replace(',', ''))
                    break

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
            'collected': hero_collected,
        }

    def parse_tournament_file(self, filepath: str) -> list[dict]:
        """Parse a GGPoker tournament hand history file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        hands = content.split('\n\n\n')
        parsed = []

        for hand_text in hands:
            if not hand_text.strip():
                continue
            hand = self.parse_tournament_hand(hand_text)
            if hand:
                parsed.append(hand)

        return parsed
