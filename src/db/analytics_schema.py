"""Analytics database schema definitions.

Separate SQLite database (analytics.db) for storing pre-processed
analysis results.  This is a persistence layer on top of the existing
analysers – the analysers themselves remain unchanged.
"""

ANALYTICS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS analytics_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS global_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    stat_name TEXT NOT NULL,
    stat_value REAL,
    stat_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    session_key TEXT NOT NULL,
    stat_name TEXT NOT NULL,
    stat_value REAL,
    stat_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    day TEXT NOT NULL,
    stat_name TEXT NOT NULL,
    stat_value REAL,
    stat_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positional_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    position TEXT NOT NULL,
    stat_name TEXT NOT NULL,
    stat_value REAL,
    stat_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stack_depth_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    tier TEXT NOT NULL,
    stat_name TEXT NOT NULL,
    stat_value REAL,
    stat_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leak_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    leak_name TEXT NOT NULL,
    category TEXT,
    stat_name TEXT,
    current_value REAL,
    healthy_low REAL,
    healthy_high REAL,
    cost_bb100 REAL,
    direction TEXT,
    suggestion TEXT,
    position TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tilt_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    analysis_key TEXT NOT NULL,
    stat_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ev_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    stat_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bet_sizing_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    sizing_key TEXT NOT NULL,
    stat_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hand_matrix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    position TEXT NOT NULL,
    hand_combo TEXT NOT NULL,
    dealt INTEGER DEFAULT 0,
    played INTEGER DEFAULT 0,
    total_net REAL DEFAULT 0,
    bb100 REAL DEFAULT 0,
    action_breakdown TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS redline_blueline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_type TEXT NOT NULL,
    data_key TEXT NOT NULL,
    stat_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_global_stats_game ON global_stats(game_type);
CREATE INDEX IF NOT EXISTS idx_session_stats_game ON session_stats(game_type);
CREATE INDEX IF NOT EXISTS idx_daily_stats_game ON daily_stats(game_type);
CREATE INDEX IF NOT EXISTS idx_positional_stats_game ON positional_stats(game_type);
CREATE INDEX IF NOT EXISTS idx_stack_depth_stats_game ON stack_depth_stats(game_type);
CREATE INDEX IF NOT EXISTS idx_leak_analysis_game ON leak_analysis(game_type);
CREATE INDEX IF NOT EXISTS idx_tilt_analysis_game ON tilt_analysis(game_type);
CREATE INDEX IF NOT EXISTS idx_ev_analysis_game ON ev_analysis(game_type);
CREATE INDEX IF NOT EXISTS idx_bet_sizing_game ON bet_sizing_stats(game_type);
CREATE INDEX IF NOT EXISTS idx_hand_matrix_game ON hand_matrix(game_type);
CREATE INDEX IF NOT EXISTS idx_redline_game ON redline_blueline(game_type);
"""


def init_analytics_db(conn):
    """Initialize the analytics database schema."""
    conn.executescript(ANALYTICS_SCHEMA_SQL)
    conn.commit()
