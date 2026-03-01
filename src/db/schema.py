"""SQLite database schema definitions."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hands (
    hand_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    game_type TEXT NOT NULL,
    date TEXT NOT NULL,
    blinds_sb REAL,
    blinds_bb REAL,
    hero_cards TEXT,
    hero_position TEXT,
    invested REAL DEFAULT 0,
    won REAL DEFAULT 0,
    net REAL DEFAULT 0,
    rake REAL DEFAULT 0,
    table_name TEXT,
    num_players INTEGER,
    board_flop TEXT,
    board_turn TEXT,
    board_river TEXT,
    pot_total REAL,
    opponent_cards TEXT,
    has_allin INTEGER DEFAULT 0,
    allin_street TEXT,
    tournament_id TEXT
);

CREATE TABLE IF NOT EXISTS hand_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id TEXT NOT NULL,
    street TEXT NOT NULL,
    player TEXT NOT NULL,
    action_type TEXT NOT NULL,
    amount REAL DEFAULT 0,
    is_hero INTEGER DEFAULT 0,
    sequence_order INTEGER DEFAULT 0,
    position TEXT,
    is_voluntary INTEGER DEFAULT 0,
    FOREIGN KEY (hand_id) REFERENCES hands(hand_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT,
    date TEXT NOT NULL,
    buy_in REAL DEFAULT 0,
    cash_out REAL DEFAULT 0,
    profit REAL DEFAULT 0,
    hands_count INTEGER DEFAULT 0,
    min_stack REAL DEFAULT 0,
    start_time TEXT,
    end_time TEXT
);

CREATE TABLE IF NOT EXISTS tournaments (
    tournament_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    name TEXT,
    date TEXT,
    buy_in REAL DEFAULT 0,
    rake REAL DEFAULT 0,
    bounty REAL DEFAULT 0,
    total_buy_in REAL DEFAULT 0,
    position INTEGER,
    prize REAL DEFAULT 0,
    bounty_won REAL DEFAULT 0,
    total_players INTEGER DEFAULT 0,
    entries INTEGER DEFAULT 1,
    is_bounty INTEGER DEFAULT 0,
    is_satellite INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tournament_summaries (
    tournament_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    name TEXT,
    date TEXT,
    buy_in REAL DEFAULT 0,
    rake REAL DEFAULT 0,
    bounty REAL DEFAULT 0,
    total_buy_in REAL DEFAULT 0,
    position INTEGER,
    prize REAL DEFAULT 0,
    bounty_won REAL DEFAULT 0,
    total_players INTEGER DEFAULT 0,
    entries INTEGER DEFAULT 1,
    is_bounty INTEGER DEFAULT 0,
    is_satellite INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS imported_files (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    records_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_hands_date ON hands(date);
CREATE INDEX IF NOT EXISTS idx_hands_platform ON hands(platform);
CREATE INDEX IF NOT EXISTS idx_hands_game_type ON hands(game_type);
CREATE INDEX IF NOT EXISTS idx_hand_actions_hand_id ON hand_actions(hand_id);
CREATE INDEX IF NOT EXISTS idx_hand_actions_street ON hand_actions(hand_id, street);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
CREATE INDEX IF NOT EXISTS idx_tournaments_date ON tournaments(date);
CREATE INDEX IF NOT EXISTS idx_tournaments_platform ON tournaments(platform);
"""


MIGRATION_SQL = """
-- Add board columns to hands table (safe for existing DBs)
ALTER TABLE hands ADD COLUMN board_flop TEXT;
ALTER TABLE hands ADD COLUMN board_turn TEXT;
ALTER TABLE hands ADD COLUMN board_river TEXT;
-- Add position/voluntary columns to hand_actions table
ALTER TABLE hand_actions ADD COLUMN position TEXT;
ALTER TABLE hand_actions ADD COLUMN is_voluntary INTEGER DEFAULT 0;
"""


def init_db(conn):
    """Initialize the database schema."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    _run_migrations(conn)


def _run_migrations(conn):
    """Run schema migrations for existing databases."""
    cursor = conn.execute("PRAGMA table_info(hands)")
    hand_cols = {row[1] for row in cursor.fetchall()}
    if 'board_flop' not in hand_cols:
        conn.execute("ALTER TABLE hands ADD COLUMN board_flop TEXT")
        conn.execute("ALTER TABLE hands ADD COLUMN board_turn TEXT")
        conn.execute("ALTER TABLE hands ADD COLUMN board_river TEXT")
        conn.commit()

    cursor = conn.execute("PRAGMA table_info(hand_actions)")
    action_cols = {row[1] for row in cursor.fetchall()}
    if 'position' not in action_cols:
        conn.execute("ALTER TABLE hand_actions ADD COLUMN position TEXT")
        conn.execute("ALTER TABLE hand_actions ADD COLUMN is_voluntary INTEGER DEFAULT 0")
        conn.commit()

    # US-004: Add showdown/all-in columns to hands table
    if 'pot_total' not in hand_cols:
        conn.execute("ALTER TABLE hands ADD COLUMN pot_total REAL")
        conn.execute("ALTER TABLE hands ADD COLUMN opponent_cards TEXT")
        conn.execute("ALTER TABLE hands ADD COLUMN has_allin INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE hands ADD COLUMN allin_street TEXT")
        conn.commit()

    # US-006: Add tournament_id column to hands table
    if 'tournament_id' not in hand_cols:
        conn.execute("ALTER TABLE hands ADD COLUMN tournament_id TEXT")
        conn.commit()
