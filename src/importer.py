"""Import pipeline for poker hand histories.

Handles ZIP extraction, file deduplication via hashing,
parsing, and database insertion.
"""

import hashlib
import zipfile
from collections import defaultdict
from pathlib import Path

from src.db.connection import get_connection
from src.db.repository import Repository
from src.parsers.ggpoker import GGPokerParser
from src.parsers.pokerstars import PokerStarsParser


def _file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def extract_zip_files(folder_path: str) -> int:
    """Extract all .zip files in a folder. Returns count extracted."""
    folder = Path(folder_path)
    if not folder.exists():
        return 0

    zip_files = list(folder.glob('*.zip'))
    extracted = 0
    for zf in zip_files:
        try:
            print(f"  Extracting {zf.name}...")
            with zipfile.ZipFile(zf, 'r') as zip_ref:
                zip_ref.extractall(folder)
            extracted += 1
        except Exception as e:
            print(f"  Warning: error extracting {zf.name}: {e}")
    return extracted


class Importer:
    """Incremental import pipeline."""

    def __init__(self, db_path: str = 'poker.db'):
        self.conn = get_connection(db_path)
        self.repo = Repository(self.conn)
        self.gg_parser = GGPokerParser()
        self.ps_parser = PokerStarsParser()

    def import_all(self, force: bool = False, source: str = 'all'):
        """Run the full import pipeline.

        Args:
            force: If True, re-import files even if hash matches.
            source: 'cash', 'tournament', or 'all'.
        """
        print("Checking for ZIP files...")
        self._extract_zips()
        print()

        if source in ('cash', 'all'):
            self._import_cash_hands(force)

        if source in ('tournament', 'all'):
            self._import_tournament_summaries(force)
            self._import_tournament_hands(force)

        if source in ('cash', 'all'):
            self._compute_sessions()

        print()
        print(f"Database: {self.repo.get_hands_count()} hands, "
              f"{self.repo.get_tournaments_count()} tournaments, "
              f"{self.repo.get_imported_files_count()} files tracked")

    def _extract_zips(self):
        """Extract ZIP files from all data folders."""
        folders = ['data/cash', 'data/tournament', 'data/tournament-summary', 'data/pokerstars']
        total = 0
        for folder in folders:
            n = extract_zip_files(folder)
            if n > 0:
                print(f"  {n} ZIP(s) extracted from {folder}/")
                total += n
        if total == 0:
            print("  No ZIP files found.")

    def _import_cash_hands(self, force: bool):
        """Import cash hand history files."""
        cash_path = Path('data/cash')
        if not cash_path.exists():
            print("data/cash/ not found, skipping cash import.")
            return

        files = list(cash_path.glob('*.txt'))
        if not files:
            print("No cash hand files found.")
            return

        print(f"Importing {len(files)} cash hand file(s)...")
        total_inserted = 0
        skipped_files = 0

        for filepath in files:
            fpath_str = str(filepath)
            fhash = _file_hash(fpath_str)

            if not force and self.repo.is_file_imported(fpath_str, fhash):
                skipped_files += 1
                continue

            hands = self.gg_parser.parse_hand_file(fpath_str)
            inserted = self.repo.insert_hands_batch(hands)
            self.repo.mark_file_imported(fpath_str, fhash, inserted)
            total_inserted += inserted
            print(f"  {filepath.name}: {inserted} hands imported")

        if skipped_files:
            print(f"  {skipped_files} file(s) already imported (skipped)")
        print(f"  Total: {total_inserted} new cash hands imported")

    def _import_tournament_summaries(self, force: bool):
        """Import tournament summary files."""
        summary_path = Path('data/tournament-summary')
        if not summary_path.exists():
            print("data/tournament-summary/ not found, skipping summaries.")
            return

        files = list(summary_path.glob('*.txt'))
        if not files:
            print("No tournament summary files found.")
            return

        print(f"Importing {len(files)} tournament summary file(s)...")
        total_inserted = 0
        skipped_files = 0

        for filepath in files:
            fpath_str = str(filepath)
            fhash = _file_hash(fpath_str)

            if not force and self.repo.is_file_imported(fpath_str, fhash):
                skipped_files += 1
                continue

            summary = self.gg_parser.parse_summary_file(fpath_str)
            if summary:
                if self.repo.insert_tournament_summary(summary):
                    total_inserted += 1
                self.repo.mark_file_imported(fpath_str, fhash, 1)

        if skipped_files:
            print(f"  {skipped_files} file(s) already imported (skipped)")
        print(f"  Total: {total_inserted} new tournament summaries imported")

    def _import_tournament_hands(self, force: bool):
        """Import tournament hand history files and build tournament records."""
        # GGPoker tournaments
        tournament_path = Path('data/tournament')
        gg_hands = []
        if tournament_path.exists():
            files = list(tournament_path.glob('*.txt'))
            if files:
                print(f"Importing {len(files)} GGPoker tournament file(s)...")
                skipped = 0
                for filepath in files:
                    fpath_str = str(filepath)
                    fhash = _file_hash(fpath_str)
                    if not force and self.repo.is_file_imported(fpath_str, fhash):
                        skipped += 1
                        continue
                    hands = self.gg_parser.parse_tournament_file(fpath_str)
                    gg_hands.extend(hands)
                    self.repo.mark_file_imported(fpath_str, fhash, len(hands))
                if skipped:
                    print(f"  {skipped} file(s) already imported (skipped)")

        # PokerStars tournaments
        ps_path = Path('data/pokerstars')
        ps_summaries = {}
        ps_hands = []
        if ps_path.exists():
            files = list(ps_path.glob('**/*.txt'))
            if files:
                print(f"Importing {len(files)} PokerStars tournament file(s)...")
                skipped = 0
                for filepath in files:
                    fpath_str = str(filepath)
                    fhash = _file_hash(fpath_str)
                    if not force and self.repo.is_file_imported(fpath_str, fhash):
                        skipped += 1
                        continue
                    hands, summary = self.ps_parser.parse_tournament_file(fpath_str)
                    ps_hands.extend(hands)
                    if summary:
                        ps_summaries[summary['tournament_id']] = summary
                    self.repo.mark_file_imported(fpath_str, fhash, len(hands))
                if skipped:
                    print(f"  {skipped} file(s) already imported (skipped)")

        # Build tournament records from hands
        all_tournament_hands = gg_hands + ps_hands
        if all_tournament_hands:
            self._build_tournaments(all_tournament_hands, ps_summaries)

    def _build_tournaments(self, all_hands: list[dict], ps_summaries: dict):
        """Build tournament records from parsed hands and summaries."""
        # Get summaries from DB
        db_summaries = self.repo.get_tournament_summaries()

        # Group hands by tournament
        by_tournament = defaultdict(list)
        for hand in all_hands:
            by_tournament[hand['tournament_id']].append(hand)

        inserted = 0
        for tournament_id, hands in by_tournament.items():
            hands.sort(key=lambda x: x['date'])
            tournament_name = hands[0]['tournament_name']
            start_date = hands[0]['date']

            # Detect rebuys
            rebuy_count = 0
            previous_stack = None
            for hand in hands:
                if previous_stack is not None and previous_stack == 0 and hand['stack'] > 1000:
                    rebuy_count += 1
                previous_stack = hand['stack']

            # Get summary data (DB first, then PS inline)
            summary = db_summaries.get(tournament_id) or ps_summaries.get(tournament_id)

            if summary:
                buy_in_unit = summary.get('total_buy_in', 0)
                buy_in = summary.get('buy_in', 0)
                rake = summary.get('rake', 0)
                bounty_val = summary.get('bounty', 0)
                is_bounty = bool(summary.get('is_bounty', 0))
                prize = summary.get('prize', 0)
                position = summary.get('position')
                total_players = summary.get('total_players', 0)
                reentries = summary.get('reentries', summary.get('entries', 1) - 1)
                entries = 1 + reentries
            else:
                buy_in_unit = self._extract_buy_in_from_name(tournament_name)
                buy_in = buy_in_unit
                rake = 0.0
                bounty_val = 0.0
                is_bounty = False
                prize = 0.0
                position = None
                total_players = 0
                entries = 1 + rebuy_count

            name_lower = tournament_name.lower()
            is_satellite = any(
                kw in name_lower
                for kw in ['satellite', 'step', 'spin', 'mega to', 'sop express', 'wsop express']
            )

            t = {
                'tournament_id': tournament_id,
                'platform': 'PokerStars' if tournament_id.startswith('PS') else 'GGPoker',
                'name': tournament_name,
                'date': start_date,
                'buy_in': buy_in,
                'rake': rake,
                'bounty': bounty_val,
                'total_buy_in': buy_in_unit,
                'position': position,
                'prize': prize,
                'bounty_won': 0.0,
                'total_players': total_players,
                'entries': entries,
                'is_bounty': is_bounty,
                'is_satellite': is_satellite,
            }

            if self.repo.insert_tournament(t):
                inserted += 1

        self.conn.commit()
        print(f"  {inserted} new tournament(s) imported")

    def _extract_buy_in_from_name(self, name: str) -> float:
        """Extract buy-in value from tournament name (fallback)."""
        import re

        match = re.search(r'^\$?(\d+(?:\.\d+)?)\s', name)
        if match:
            return float(match.group(1))

        match = re.search(r'\s\$?(\d+(?:\.\d+)?)\s*$', name)
        if match:
            return float(match.group(1))

        if 'freeroll' in name.lower():
            return 0.0

        match = re.search(r'\$?(\d+(?:\.\d+)?)', name)
        if match:
            return float(match.group(1))

        return 0.0

    def _compute_sessions(self):
        """Compute cash game sessions from imported hands."""
        hands = self.repo.get_cash_hands()
        if not hands:
            return

        self.repo.clear_sessions()

        # Sort by date
        from datetime import datetime as dt
        for h in hands:
            if isinstance(h['date'], str):
                h['_date'] = dt.fromisoformat(h['date'])
            else:
                h['_date'] = h['date']

        hands.sort(key=lambda x: x['_date'])

        sessions = []
        current = None
        running_total = 0.0

        for hand in hands:
            stack_before = hand.get('invested', 0) + hand.get('net', 0)
            # Approximate stack_before from first hand investment
            # For session detection we use a simpler heuristic

            if current is None:
                current = {
                    'platform': hand.get('platform', 'GGPoker'),
                    'start_time': hand['_date'],
                    'end_time': hand['_date'],
                    'hands': [hand],
                    'min_stack': 0,
                    'buy_in': 0,
                }
                running_total = hand.get('net', 0)
            else:
                last_date = current['hands'][-1]['_date'].date()
                curr_date = hand['_date'].date()

                if last_date != curr_date:
                    # Day changed - finalize session
                    current['end_time'] = current['hands'][-1]['_date']
                    current['hands_count'] = len(current['hands'])
                    current['profit'] = running_total
                    current['cash_out'] = current['buy_in'] + running_total
                    sessions.append(current)

                    current = {
                        'platform': hand.get('platform', 'GGPoker'),
                        'start_time': hand['_date'],
                        'end_time': hand['_date'],
                        'hands': [hand],
                        'min_stack': 0,
                        'buy_in': 0,
                    }
                    running_total = hand.get('net', 0)
                else:
                    current['hands'].append(hand)
                    running_total += hand.get('net', 0)

        # Finalize last session
        if current:
            current['end_time'] = current['hands'][-1]['_date']
            current['hands_count'] = len(current['hands'])
            current['profit'] = running_total
            current['cash_out'] = current['buy_in'] + running_total
            sessions.append(current)

        for session in sessions:
            self.repo.insert_session(session)

        print(f"  {len(sessions)} session(s) computed")
