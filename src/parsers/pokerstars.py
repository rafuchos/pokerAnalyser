"""PokerStars hand history parser.

Extracts PokerStars parsing logic from poker_tournament_analyzer.py.
"""

import re
from datetime import datetime
from typing import Optional

from src.parsers.base import BaseParser, HandData, TournamentSummaryData


class PokerStarsParser(BaseParser):
    """Parser for PokerStars hand histories."""

    platform = 'PokerStars'

    def __init__(self, hero_name: str = 'gangsta221'):
        self.hero_name = hero_name

    def parse_hand_file(self, filepath: str) -> list[HandData]:
        """Parse a PokerStars cash hand history file (not yet implemented)."""
        return []

    def parse_summary_file(self, filepath: str) -> Optional[TournamentSummaryData]:
        """Parse a PokerStars tournament (embedded in hand history file)."""
        return None

    def parse_tournament_file(self, filepath: str) -> tuple[list[dict], Optional[dict]]:
        """Parse a PokerStars tournament hand history file.

        Returns:
            Tuple of (parsed_hands, summary_dict) where summary_dict
            contains tournament-level info (buy-in, prize, position, etc.)
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        header_match = re.search(
            r"Tournament #(\d+),\s*\$([\d.]+)\+\$([\d.]+)(?:\+\$([\d.]+))?\s*USD",
            content
        )
        if not header_match:
            return [], None

        tournament_id = 'PS' + header_match.group(1)
        buy_in_part = float(header_match.group(2))
        rake_part = 0.0
        bounty_part = 0.0

        if header_match.group(4):
            bounty_part = float(header_match.group(3))
            rake_part = float(header_match.group(4))
        else:
            rake_part = float(header_match.group(3))

        is_bounty = bounty_part > 0
        total_buy_in_unit = buy_in_part + bounty_part + rake_part

        if is_bounty:
            tournament_name = f"[PS] Bounty ${total_buy_in_unit:.2f}"
        else:
            tournament_name = f"[PS] MTT ${total_buy_in_unit:.2f}"

        # Count re-entries
        reentries = len(re.findall(
            rf'{re.escape(self.hero_name)} finished the tournament\s*\n', content
        ))

        # Final position and prize
        position = None
        position_prize = 0.0
        finish_match = re.search(
            rf'{re.escape(self.hero_name)} finished the tournament in (\d+)(?:st|nd|rd|th) place'
            rf'(?:\s+and received \$([\d,.]+)\.)?',
            content
        )
        if finish_match:
            position = int(finish_match.group(1))
            if finish_match.group(2):
                position_prize = float(finish_match.group(2).replace(',', ''))

        # Bounty wins
        bounty_wins = re.findall(
            rf'{re.escape(self.hero_name)} wins \$([\d,.]+) for eliminating', content
        )
        total_bounties = sum(float(b.replace(',', '')) for b in bounty_wins)

        prize = position_prize + total_bounties

        summary = {
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
            'is_bounty': is_bounty,
        }

        # Parse individual hands
        hands_raw = content.split('\n\n\n')
        parsed = []

        for hand_text in hands_raw:
            if not hand_text.strip():
                continue
            hand = self._parse_single_hand(hand_text, tournament_id, tournament_name)
            if hand:
                parsed.append(hand)

        return parsed, summary

    def _parse_single_hand(self, hand_text: str, tournament_id: str,
                           tournament_name: str) -> Optional[dict]:
        """Parse a single PokerStars tournament hand."""
        lines = hand_text.strip().split('\n')
        if not lines:
            return None

        header_match = re.search(
            r"PokerStars Hand #(\d+): Tournament #(\d+),.+?"
            r"Level\s*(\w+)\s*\((\d+)/(\d+)\)\s*-\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})",
            lines[0]
        )
        if not header_match:
            return None

        hand_id = 'PS' + header_match.group(1)
        level_str = header_match.group(3)
        try:
            level = int(level_str)
        except ValueError:
            roman_map = {
                'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6,
                'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10, 'XI': 11, 'XII': 12,
                'XIII': 13, 'XIV': 14, 'XV': 15, 'XVI': 16, 'XVII': 17,
                'XVIII': 18, 'XIX': 19, 'XX': 20, 'XXI': 21, 'XXII': 22,
                'XXIII': 23, 'XXIV': 24, 'XXV': 25, 'XXVI': 26, 'XXVII': 27,
                'XXVIII': 28, 'XXIX': 29, 'XXX': 30,
            }
            level = roman_map.get(level_str, 1)

        small_blind = int(header_match.group(4))
        big_blind = int(header_match.group(5))
        date_str = header_match.group(6)
        hand_date = datetime.strptime(date_str, '%Y/%m/%d %H:%M:%S')

        hero_starting_stack = 0
        hero_collected = 0
        hero_pattern = re.escape(self.hero_name)

        for line in lines:
            if re.search(rf'Seat \d+: {hero_pattern} \((\d+[\d,]*) in chips', line):
                stack_match = re.search(rf'{hero_pattern} \((\d+[\d,]*) in chips', line)
                if stack_match:
                    hero_starting_stack = int(stack_match.group(1).replace(',', ''))
                    break

        for line in lines:
            if f'{self.hero_name} collected' in line:
                collected_match = re.search(rf'{hero_pattern} collected ([\d,]+)', line)
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
