"""Base class for poker hand history parsers."""

from abc import ABC, abstractmethod
from typing import Optional


class HandData:
    """Parsed data for a single cash game hand."""
    __slots__ = (
        'hand_id', 'platform', 'game_type', 'date', 'blinds_sb', 'blinds_bb',
        'hero_cards', 'hero_position', 'invested', 'won', 'net', 'rake',
        'table_name', 'num_players',
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


class TournamentSummaryData:
    """Parsed data for a tournament summary."""
    __slots__ = (
        'tournament_id', 'platform', 'name', 'date', 'buy_in', 'rake',
        'bounty', 'total_buy_in', 'position', 'prize', 'bounty_won',
        'total_players', 'entries', 'is_bounty', 'is_satellite',
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))


class BaseParser(ABC):
    """Abstract base class for poker hand history parsers."""

    platform: str = ''

    @abstractmethod
    def parse_hand_file(self, filepath: str) -> list[HandData]:
        """Parse a hand history file and return a list of HandData objects."""

    @abstractmethod
    def parse_summary_file(self, filepath: str) -> Optional[TournamentSummaryData]:
        """Parse a tournament summary file."""
