# Poker Analyzer - Hand History Analysis Suite

Multi-platform poker analyzer for **GGPoker** and **PokerStars**. Parses hand histories to generate detailed HTML reports with daily summaries, session tracking, and profit/loss analysis for cash games, tournaments, and satellite cycles.

## Folder Structure

```
CashHandTracking/
├── data/
│   ├── cash/                # GG cash game hand histories (.txt / .zip)
│   ├── tournament/          # GG tournament hand histories (.txt / .zip)
│   ├── tournament-summary/  # GG tournament summary files (.txt / .zip)
│   └── pokerstars/          # PokerStars hand histories (.txt)
├── poker_cash_analyzer.py          # Cash game analyzer
├── poker_tournament_analyzer.py    # Tournament analyzer (GG + PS)
├── poker_spin_analyzer.py          # Spin & Gold / WSOP Express cycle analyzer
├── generate_reports.py             # Unified report generator
└── README.md
```

## How to Use

### Generate All Reports (Recommended)

```bash
python generate_reports.py
```

This will:
- Extract `.zip` files automatically from all data folders
- Analyze GG cash games from `data/cash/`
- Analyze GG + PokerStars tournaments from `data/tournament/` and `data/pokerstars/`
- Generate HTML reports

**Generated reports:**
- `cash_report.html` - Cash game report
- `tournament_report.html` - Tournament report (GG + PokerStars combined)

### Spin & Gold Cycle Analysis

```bash
python poker_spin_analyzer.py
```

Generates `spin_report.html` - Analyzes the Spin & Gold $2 → WSOP Express $10 satellite cycle profitability.

## Supported Platforms

### GGPoker
- **Cash games**: Hand histories from Rush & Cash or regular tables
- **Tournaments**: Hand histories + summary files for prize/position data
- **Hero identification**: `Hero`

### PokerStars
- **Tournaments**: Hand histories with buy-in, bounty, and result parsing
- **Hero identification**: Configurable (default: `gangsta221`)
- **Bounty detection**: Parsed from seat lines and elimination events

## Cash Game Analysis

- **Automatic session detection**: Based on bust (stack → $0) or day change
- **Per-day stats**: Hands played, sessions, total invested, profit/loss, notable hands
- **Buy-in calculation**: Smart detection of real buy-ins vs reloads
- **Supports values > $1,000**: Handles comma-separated monetary values

## Tournament Analysis

- **Multi-platform**: Combines GG and PokerStars tournaments in a single report
- **Buy-in extraction**: From tournament name (GG) or header (PS)
- **Bounty tracking**: Detects bounty tournaments, tracks bounty wins separately
- **Re-entry detection**: Counts re-entries from stack resets or summary files
- **ITM tracking**: In The Money count (excludes bounty-only prizes)
- **Satellite separation**: Spin & Gold, WSOP Express, Steps, and Satellites tracked separately from main tournament stats
- **Prize extraction**: From summary files (GG) or hand history (PS)

## Setup

### Requirements
- Python 3.6+
- Standard library only (no external dependencies)

### Getting Started

1. Clone the repo
2. Place your hand history files in the appropriate `data/` subfolders:
   - GG cash: `data/cash/` (.txt or .zip)
   - GG tournaments: `data/tournament/` (.txt or .zip)
   - GG summaries: `data/tournament-summary/` (.txt or .zip)
   - PokerStars: `data/pokerstars/` (.txt)
3. Run `python generate_reports.py`
4. Open the generated `.html` files in your browser

## HTML Reports

### Cash Games (Green theme)
- Dark theme with green accents (#00ff88)
- Daily breakdown with session details
- Notable hands highlight (biggest win/loss per day)

### Tournaments (Orange theme)
- Dark theme with orange accents (#ff8800)
- Daily breakdown with individual tournament details
- Satellite section with dedicated stats
- Color-coded results: green = ITM, red = busted

## License

Personal project for poker analysis.
