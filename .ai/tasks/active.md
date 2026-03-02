# Active Tasks

This file tracks work currently in progress.

## Format

Use checkboxes to track completion status:

```markdown
- [x] US-001: Pending task (2026-02-28)
- [x] US-002: Completed task
```

Each task can have:
- **Status indicator:** [ ] = pending, [x] = completed
- **ID:** US-XXX, BUG-XXX, DEV-XXX, or SPIKE-XXX
- **Title:** Clear, actionable description
- **Notes:** Optional context or blockers
- **Assignee:** Who's working on it (optional)

---

## Task Types

- **US-XXX:** User Story (feature work)
- **BUG-XXX:** Bug fix
- **DEV-XXX:** Developer task (refactoring, tech debt)
- **SPIKE-XXX:** Research or investigation
- **DOCS-XXX:** Documentation

---

## Management Rules

1. **Limit WIP:** Keep 3-5 tasks active max
2. **Prioritize:** Order from highest to lowest priority
3. **Clarify blockers:** Note if task is blocked
4. **Update daily:** Check boxes as you work
5. **Archive completion:** Move finished tasks to backlog with date

---

## Template for New Task

```markdown
- [ ] US-XXX: [Clear title]
  - Assignee: (your name or team)
  - Priority: High/Medium/Low
  - Blocked by: (if applicable)
  - Notes: (context)
```

---

## Current Sprint

Update this section weekly with sprint goals and dates.

**Sprint:** YYYY-MM-DD to YYYY-MM-DD
**Goal:** (What we're trying to accomplish)
**Capacity:** (Team capacity/points)

---

## Today's Focus

- [x] US-000: Reestruturação do Projeto + Banco SQLite com Import Pipeline (2026-02-28)
- [x] US-001: Parser de Ações Detalhadas por Street (2026-02-28)
- [x] US-002: Cálculo de VPIP, PFR e Estatísticas Preflop do Hero (2026-02-28)
- [x] US-003: Estatísticas Postflop: AF, WTSD, W$SD, CBet (2026-02-28)
- [x] US-004: Análise de Expected Value (EV) e All-In Equity (2026-02-28)
- [x] US-005: Relatório Diário com Breakdown por Sessão e Stats de Jogo (2026-02-28)
- [x] US-006: Poker Stats Completas para Torneios (2026-03-01)
- [x] US-007: Relatório de Torneios por Sessão (2026-03-02)
- [x] US-008: EV Analysis por Sessão (Cash e Torneio) (2026-03-02)
- [x] US-009: EV Completo para Todas as Decisões (Decision-Tree EV) (2026-03-02)
- [x] US-010: Análise Posicional Completa (Stats + Win Rate por Posição) (2026-03-02)
- [x] US-013: Análise de Bet Sizing e Pot-Type Segmentation (2026-03-02)
- [x] US-012: Red Line / Blue Line (Non-Showdown vs Showdown Winnings) (2026-03-02)
- [x] US-011: Leak Finder Automatizado com Spots de Estudo Priorizados (2026-03-02)

---

## Completed

- [x] US-012: Red Line / Blue Line (Non-Showdown vs Showdown Winnings) (2026-03-02)
  - CashAnalyzer.get_redline_blueline(): cumulative profit split by showdown/non-showdown
  - CashAnalyzer._compute_redline_by_session(): per-session breakdown
  - CashAnalyzer._hand_went_to_showdown(): static method (opponent_cards or postflop remaining players)
  - TournamentAnalyzer.get_redline_blueline(): tournament version with per-day breakdown
  - Module helpers: _downsample_redline() (max 500 points), _generate_redline_diagnostics()
  - Diagnostics: 'Red line caindo', 'Blue line caindo', 'Alta taxa de showdown'
  - cash_report.py: _render_redline_blueline_chart() (700x300 SVG, 3 polylines, grid, legend)
  - cash_report.py: _render_redline_blueline() (stats grid, chart, diagnostics, session table)
  - tournament_report.py: _render_redline_chart_tourn() (tournament SVG chart, Chips Y-axis)
  - tournament_report.py: _render_redline_blueline_tournament() (tournament HTML section)
  - Integrated into generate_cash_report() and generate_tournament_report()
  - 98 new tests (764 total)

- [x] US-011: Leak Finder Automatizado com Spots de Estudo Priorizados (2026-03-02)
  - New module: src/analyzers/leak_finder.py with Leak dataclass and LeakFinder class
  - LeakFinder._detect_preflop_leaks(): compares VPIP, PFR, 3-Bet, Fold-to-3Bet, ATS vs healthy ranges
  - LeakFinder._detect_postflop_leaks(): compares AF, WTSD, W$SD, CBet, Fold-to-CBet, Check-Raise vs ranges
  - LeakFinder._detect_positional_leaks(): per-position VPIP/PFR using position-specific ranges
  - LeakFinder._check_deviation(): computes cost in bb/100 (deviation × weight factor)
  - LeakFinder._calculate_health_score(): 0-100 score based on aggregate leak severity
  - LeakFinder._generate_study_spots(): concrete action suggestions per leak type
  - LeakFinder._compare_periods(): last 30 days vs overall stats comparison
  - CashAnalyzer.get_leak_analysis(): integration method delegating to LeakFinder
  - cash_report.py: _render_leak_finder() with top 5 leaks, priority badges, study spots
  - cash_report.py: _render_health_score_bar() visual health meter (0-100)
  - cash_report.py: _render_period_comparison() table (overall vs recent)
  - cash_report.py: _hex_to_rgb() utility for CSS color conversion
  - Integrated into generate_cash_report() after positional analysis section
  - 79 new tests (666 total)

- [x] US-010: Análise Posicional Completa (Stats + Win Rate por Posição) (2026-03-02)
  - Repository: get_cash_hands_with_position() for hand-level financial data per position
  - Repository: get_all_action_sequences() now includes ha.is_voluntary (VPIP fix)
  - CashAnalyzer: POSITION_VPIP_HEALTHY/WARNING + POSITION_PFR_HEALTHY/WARNING dicts
  - CashAnalyzer: _classify_positional_health() with position-specific thresholds
  - CashAnalyzer: _analyze_blinds_defense() detecting steal attempts for BB/SB
  - CashAnalyzer: get_positional_stats() computing full stats per position
  - CashAnalyzer: _format_positional_stats() returning by_position, blinds_defense, ats_by_pos, comparison, radar
  - CashAnalyzer: _build_radar_data() generating normalized radar chart data
  - cash_report.py: _render_positional_analysis() with full HTML section
  - cash_report.py: _render_radar_chart() generating inline SVG spider chart
  - Integrated into generate_cash_report() after postflop stats section
  - 65 new tests (587 total)

- [x] US-009: EV Completo para Todas as Decisões (Decision-Tree EV) (2026-03-02)
  - EVAnalyzer.get_decision_ev_analysis: per-street EV for fold/call/raise decisions
  - EVAnalyzer._identify_ev_leaks: top 5 leak detection from decision contexts
  - EVAnalyzer._leak_description: human-readable leak descriptions in Portuguese
  - Context detection: vs_bet (facing opponent bet) vs initiative (hero acts first)
  - Bug fix: _identify_ev_leaks ctx_key parsing for 'vs_bet' underscore
  - Cash report: _render_decision_ev_analysis with per-street table
  - Cash report: _render_decision_ev_chart (inline SVG bar chart)
  - Cash report: EV leaks section with ranked cards, stats, and suggestions
  - All-in EV maintained as sub-section within Decision Tree section
  - CSS: .leak-card, .leak-header, .leak-rank, .leak-suggestion styles
  - 53 new tests (522 total)


- [x] US-008: EV Analysis por Sessão (Cash e Torneio) (2026-03-02)
  - EVAnalyzer.get_session_ev_analysis: per-session EV for cash games (all-in hands, chart_data)
  - CashAnalyzer.get_session_details: ev_data included when ev_analyzer passed
  - CashAnalyzer.get_daily_reports_with_sessions: ev_data flows through to each session
  - TournamentAnalyzer._get_daily_ev_analysis: chart_data added for mini EV sparkline
  - Cash report: _render_session_ev_summary with Lucky/Unlucky badge per session
  - Cash report: _render_mini_ev_chart (300x60 SVG, Real green vs EV orange dashed)
  - Tournament report: _render_session_ev_summary with Lucky/Unlucky badge per day
  - Tournament report: _render_mini_ev_chart (300x60 SVG, Real orange vs EV blue dashed)
  - Global EV maintained at top of both reports (complementary, not replaced)
  - 40 new tests (469 total)


- [x] US-007: Relatório de Torneios por Sessão (2026-03-02)
  - Session-focused daily layout: aggregated stats as primary view, not individual tournament details
  - Day-level aggregated stats with health badges (VPIP, PFR, 3-Bet, AF, WTSD, W$SD, CBet)
  - Session financial summary: total invested, total won, net, ROI, ITM rate per day
  - Session sparkline: aggregated chip evolution across all tournaments of the day
  - Session-level notable hands: biggest win/loss across all day's tournaments
  - Session-level EV analysis: day-filtered EV with bb/100, luck factor
  - Cross-day session comparison: best/worst sessions by net, ROI, ITM, hands, stats
  - Tournament details demoted to accordion (collapsed by default)
  - Tournament comparison within day preserved inside session view
  - 67 new tests (429 total)

- [x] US-006: Poker Stats Completas para Torneios (2026-03-01)
  - Schema: tournament_id column on hands table with migration
  - Parsers: parse_tournament_single_hand() for GGPoker and PokerStars
  - Repository: tournament hand queries (hands, preflop/all actions, allin, count)
  - Importer: tournament hand import pipeline with actions, board, positions, showdown
  - Analyzer: TournamentAnalyzer with VPIP/PFR/3Bet/AF/WTSD/CBet stats, health badges
  - EV analysis with variable BB normalization (bb/100 per-hand blind levels)
  - Daily reports with per-tournament breakdown, weighted averages, comparison table
  - Report: full HTML rendering with global stats, inline SVG EV chart, chip sparklines
  - Per-tournament stats with health badges, notable hands, tournament comparison
  - Orange theme (#ff8800) for tournament reports
  - 57 new tests (362 total)

- [x] US-005: Relatório Diário com Breakdown por Sessão e Stats de Jogo (2026-02-28)
  - Expandable accordion session cards within each daily report
  - Session info: start/end time, duration, buy-in, cash-out, profit, hands played, min stack
  - Per-session game stats: VPIP%, PFR%, 3-Bet%, AF, WTSD%, W$SD%, CBet% with health badges
  - Inline SVG sparkline showing session profit evolution (stack over hands)
  - Notable hands (biggest win/loss) moved into corresponding session cards
  - Day summary with weighted average stats from all sessions
  - Session comparison table (best/worst per stat highlighted green/red)
  - Responsive layout with CSS media queries (desktop/tablet/mobile)
  - JavaScript accordion toggle for expandable session cards
  - Repository methods: get_hands_for_session, get_actions_for_session
  - 48 new tests (305 total)


- [x] US-004: Análise de Expected Value (EV) e All-In Equity (2026-02-28)
  - Detect all-in situations with showdown (revealed opponent cards)
  - Calculate equity using Monte Carlo simulation + exact enumeration
  - Full 5-card hand evaluator (high card through straight flush)
  - EV-adjusted results: equity * pot - invested per all-in hand
  - Cumulative EV line vs Real line chart data (SVG inline)
  - bb/100 real and EV-adjusted calculation
  - Luck factor: real net - EV net (how much above/below EV)
  - Breakdown by stakes (different blind levels)
  - EV Analysis section in HTML report with SVG chart
  - Schema migration for pot_total, opponent_cards, has_allin, allin_street
  - 78 new tests (257 total)

- [x] US-003: Estatísticas Postflop: AF, WTSD, W$SD, CBet (2026-02-28)
  - AF (Aggression Factor): (bets + raises) / calls per street and overall
  - AFq (Aggression Frequency): (bets + raises) / (bets + raises + calls + folds) per street
  - WTSD% (Went To Showdown): % of hands that went to showdown when saw flop
  - W$SD% (Won $ at Showdown): % of hands won at showdown
  - CBet% (Continuation Bet): % of times hero bet on flop after being preflop aggressor
  - Fold to CBet%: % of times hero folded to opponent's CBet
  - Check-Raise%: % of times hero check-raised per street
  - Postflop Analysis section in HTML report with health badges
  - Per-street breakdown table (AF, AFq, Check-Raise% by flop/turn/river)
  - Weekly trends table (AF, WTSD%, W$SD%, CBet% by ISO week)
  - 53 new tests (179 total)

- [x] US-002: Cálculo de VPIP, PFR e Estatísticas Preflop do Hero (2026-02-28)
  - VPIP: % de mãos com entrada voluntária preflop (excluindo blinds)
  - PFR: % de mãos com raise preflop
  - 3-Bet%: % de re-raise preflop após raise de oponente
  - Fold to 3-Bet%: % de fold após receber 3-bet
  - ATS: % de steal attempts de CO/BTN/SB quando folda até o jogador
  - Stats agregadas: overall, por posição, por dia
  - Seção 'Player Stats' no HTML report com badges de saúde (verde/amarelo/vermelho)
  - 43 novos testes (126 total)

- [x] US-001: Parser de Ações Detalhadas por Street (2026-02-28)
  - Parse every player action (fold, call, raise, check, bet, all-in) with amounts
  - Separate actions by street: preflop, flop, turn, river
  - Identify table positions (BTN, SB, BB, UTG, MP, CO) for each player
  - Extract board cards per street (flop 3 cards, turn 1, river 1)
  - Detect VPIP (voluntary pot entry excluding forced blinds)
  - Works for both GGPoker and PokerStars hand histories
  - Persist actions in hand_actions SQLite table with schema migration
  - Backward compatible with existing financial parser and reports
  - 61 new tests (83 total passing)

- [x] US-000: Reestruturação do Projeto + Banco SQLite com Import Pipeline (2026-02-28)
  - Reorganized project structure under src/ with parsers/, db/, analyzers/, reports/
  - Implemented SQLite database with schema for hands, sessions, tournaments
  - Created incremental import pipeline with file hash deduplication
  - Built CLI entry point (main.py) with import, report, stats subcommands
  - Extracted parsers from original monolithic scripts into dedicated modules
  - Reports now read from database instead of memory
  - 22 tests passing

---

## Notes

- Check prd.json for upcoming stories
- Move completed tasks to archive or backlog with completion date
- When stuck, create SPIKE task to investigate
- Reference decisions from `memory/decisions.md`
- Flag architectural changes for team discussion
