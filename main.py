#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Poker Hand Tracking & Analysis Suite - CLI Entry Point

Replaces generate_reports.py as the unified CLI interface.
Subcommands: import, report, stats, analyze, serve
"""

import sys
import io
import argparse

# Windows encoding fix
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def cmd_import(args):
    """Import hand histories into the database."""
    from src.importer import Importer

    print("=" * 60)
    print("POKER ANALYZER - Import Pipeline")
    print("=" * 60)
    print()

    importer = Importer(db_path=args.db)
    importer.import_all(force=args.force, source=args.source)

    print()
    print("=" * 60)
    print("Import complete!")
    print("=" * 60)


def cmd_report(args):
    """Generate HTML reports from the database."""
    from src.db.connection import get_connection
    from src.db.repository import Repository
    from src.analyzers.cash import CashAnalyzer
    from src.analyzers.ev import EVAnalyzer
    from src.analyzers.tournament import TournamentAnalyzer
    from src.analyzers.spin import SpinAnalyzer
    from src.reports.cash_report import generate_cash_report
    from src.reports.tournament_report import generate_tournament_report
    from src.reports.spin_report import generate_spin_report

    print("=" * 60)
    print("POKER ANALYZER - Report Generation")
    print("=" * 60)
    print()

    conn = get_connection(args.db)
    repo = Repository(conn)
    report_type = args.type
    reports_generated = []

    if report_type in ('cash', 'all'):
        if repo.get_hands_count() > 0:
            print("Generating cash game report...")
            cash_analyzer = CashAnalyzer(repo)
            ev_analyzer = EVAnalyzer(repo)
            output = generate_cash_report(
                cash_analyzer, 'output/cash_report.html',
                ev_analyzer=ev_analyzer)
            reports_generated.append(('Cash Games', output))
        else:
            print("No cash hands in database. Run 'import' first.")

    if report_type in ('tournament', 'all'):
        if repo.get_tournaments_count() > 0:
            print("Generating tournament report...")
            tournament_analyzer = TournamentAnalyzer(repo)
            output = generate_tournament_report(tournament_analyzer, 'output/tournament_report.html')
            reports_generated.append(('Tournaments', output))
        else:
            print("No tournaments in database. Run 'import' first.")

    if report_type in ('spin', 'all'):
        spin_analyzer = SpinAnalyzer(repo)
        stats = spin_analyzer.get_stats()
        if stats['spin']['count'] > 0 or stats['wsop']['count'] > 0:
            print("Generating spin cycle report...")
            output = generate_spin_report(spin_analyzer, 'output/spin_report.html')
            reports_generated.append(('Spin Cycle', output))

    print()
    print("=" * 60)
    if reports_generated:
        print("Reports generated:")
        for rtype, rpath in reports_generated:
            print(f"  {rtype:15} -> {rpath}")
    else:
        print("No reports generated. Import data first: python main.py import")
    print("=" * 60)


def cmd_config(args):
    """Manage external stats targets configuration."""
    from src.config import TargetsConfig, DEFAULT_CONFIG_PATH

    config_path = getattr(args, 'config_path', None) or DEFAULT_CONFIG_PATH

    if args.init:
        if not args.force and __import__('os').path.exists(config_path):
            print(f"Config file already exists: {config_path}")
            print("Use --force to overwrite.")
            return
        TargetsConfig.save_default(config_path)
        print(f"Default config written to: {config_path}")
        print("Edit the file to customise your targets, then run:")
        print(f"  python main.py config --validate")
        return

    if args.validate:
        try:
            config = TargetsConfig.load(config_path)
        except ValueError as exc:
            print(f"Parse error: {exc}")
            return
        errors = config.validate()
        if errors:
            print(f"Config validation FAILED ({len(errors)} error(s)):")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"Config is valid: {config_path}")
            preflop_stats = list(config.healthy_ranges.keys())
            postflop_stats = list(config.postflop_healthy_ranges.keys())
            pos_count = len(config.position_vpip_healthy)
            print(f"  Preflop stats  : {', '.join(preflop_stats)}")
            print(f"  Postflop stats : {', '.join(postflop_stats)}")
            print(f"  Positions (VPIP): {pos_count} configured")
        return

    # No flag given — show current config
    try:
        config = TargetsConfig.load(config_path)
    except ValueError as exc:
        print(f"Parse error: {exc}")
        return

    print("=" * 60)
    print("CURRENT STATS TARGETS")
    print("=" * 60)
    print()
    print("Preflop:")
    for stat, rng in config.healthy_ranges.items():
        w = config.warning_ranges.get(stat, ('?', '?'))
        print(f"  {stat:<15} healthy: {list(rng)}  warning: {list(w)}")
    print()
    print("Postflop:")
    for stat, rng in config.postflop_healthy_ranges.items():
        w = config.postflop_warning_ranges.get(stat, ('?', '?'))
        print(f"  {stat:<15} healthy: {list(rng)}  warning: {list(w)}")
    print()
    print("Positional VPIP overrides:", len(config.position_vpip_healthy), "positions")
    print("Positional PFR overrides :", len(config.position_pfr_healthy), "positions")
    print()
    if not __import__('os').path.exists(config_path):
        print("(using built-in defaults — run 'python main.py config --init' to create a file)")


def cmd_analyze(args):
    """Run all analyzers and persist results to analytics.db."""
    from src.analytics_pipeline import run_analysis

    print("=" * 60)
    print("POKER ANALYZER - Analytics Pipeline")
    print("=" * 60)
    print()

    analytics_db = getattr(args, 'analytics_db', None) or 'analytics.db'

    print(f"Source DB:    {args.db}")
    print(f"Analytics DB: {analytics_db}")
    print(f"Type:         {args.type}")
    print(f"Force:        {args.force}")
    print()

    result = run_analysis(
        poker_db_path=args.db,
        analytics_db_path=analytics_db,
        force=args.force,
        analysis_type=args.type,
    )

    if result['skipped']:
        print(result['reason'])
    else:
        if result['cash_processed']:
            print("  Cash analysis:       completed")
        if result['tournament_processed']:
            print("  Tournament analysis: completed")
        print()
        print(f"Results persisted to: {analytics_db}")

    print()
    print("=" * 60)


def cmd_serve(args):
    """Start Flask web server and open browser."""
    import threading
    import webbrowser
    from src.web.app import create_app

    port = args.port
    analytics_db = getattr(args, 'analytics_db', None) or 'analytics.db'
    debug = args.debug

    print("=" * 60)
    print("POKER ANALYZER - Web Server")
    print("=" * 60)
    print()
    print(f"Analytics DB: {analytics_db}")
    print(f"Port:         {port}")
    print(f"Debug:        {debug}")
    print()

    app = create_app(analytics_db_path=analytics_db, debug=debug)

    url = f"http://127.0.0.1:{port}"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        print(f"Opening browser at {url} ...")
    print(f"Server running at {url}")
    print("Press Ctrl+C to stop.")
    print()

    app.run(host='127.0.0.1', port=port, debug=debug, use_reloader=debug)


def cmd_stats(args):
    """Show quick stats in the terminal."""
    from src.db.connection import get_connection
    from src.db.repository import Repository

    conn = get_connection(args.db)
    repo = Repository(conn)

    print("=" * 60)
    print("POKER ANALYZER - Quick Stats")
    print("=" * 60)
    print()

    stat_type = args.type

    if stat_type in ('cash', 'all'):
        cash_stats = repo.get_cash_stats_summary('2026')
        total_hands = cash_stats.get('total_hands', 0) or 0
        total_net = cash_stats.get('total_net', 0) or 0
        biggest_win = cash_stats.get('biggest_win', 0) or 0
        biggest_loss = cash_stats.get('biggest_loss', 0) or 0

        daily = repo.get_cash_daily_stats('2026')
        total_days = len(daily)

        print("CASH GAMES (2026)")
        print("-" * 40)
        print(f"  Total Hands:    {total_hands}")
        print(f"  Days Played:    {total_days}")
        print(f"  Total Net:      ${total_net:+.2f}")
        if total_days > 0:
            print(f"  Avg/Day:        ${total_net / total_days:+.2f}")
        print(f"  Biggest Win:    ${biggest_win:+.2f}")
        print(f"  Biggest Loss:   ${biggest_loss:+.2f}")
        print()

    if stat_type in ('tournament', 'all'):
        t_stats = repo.get_tournament_stats_summary('2026')
        total_tournaments = t_stats.get('total_tournaments', 0) or 0
        total_invested = t_stats.get('total_invested', 0) or 0
        total_won = t_stats.get('total_won', 0) or 0
        total_net = t_stats.get('total_net', 0) or 0
        total_rake = t_stats.get('total_rake', 0) or 0

        print("TOURNAMENTS (2026)")
        print("-" * 40)
        print(f"  Total Tournaments: {total_tournaments}")
        print(f"  Total Invested:    ${total_invested:.2f}")
        print(f"  Total Won:         ${total_won:.2f}")
        print(f"  Total Net:         ${total_net:+.2f}")
        print(f"  Total Rake:        ${total_rake:.2f}")
        if total_invested > 0:
            roi = (total_net / total_invested) * 100
            print(f"  ROI:               {roi:+.1f}%")
        print()

    # DB info
    print("DATABASE INFO")
    print("-" * 40)
    print(f"  Hands:           {repo.get_hands_count()}")
    print(f"  Tournaments:     {repo.get_tournaments_count()}")
    print(f"  Files Imported:  {repo.get_imported_files_count()}")
    print()
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        prog='poker-analyzer',
        description='Poker Hand Tracking & Analysis Suite'
    )
    parser.add_argument('--db', default='poker.db',
                        help='Path to SQLite database (default: poker.db)')

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # import subcommand
    import_parser = subparsers.add_parser('import', help='Import hand histories into database')
    import_parser.add_argument('--force', action='store_true',
                               help='Re-import files even if already imported')
    import_parser.add_argument('--source', choices=['cash', 'tournament', 'all'],
                               default='all', help='Type of data to import (default: all)')

    # report subcommand
    report_parser = subparsers.add_parser('report', help='Generate HTML reports')
    report_parser.add_argument('--type', choices=['cash', 'tournament', 'spin', 'all'],
                               default='all', help='Type of report to generate (default: all)')

    # stats subcommand
    stats_parser = subparsers.add_parser('stats', help='Show quick stats in terminal')
    stats_parser.add_argument('--type', choices=['cash', 'tournament', 'all'],
                              default='all', help='Type of stats to show (default: all)')
    stats_parser.add_argument('--days', type=int, default=30,
                              help='Number of days to look back (default: 30)')

    # config subcommand
    config_parser = subparsers.add_parser(
        'config', help='Manage external stats targets configuration'
    )
    config_parser.add_argument(
        '--init', action='store_true',
        help='Generate default config file (config/targets.yaml)'
    )
    config_parser.add_argument(
        '--validate', action='store_true',
        help='Validate the config file and report errors'
    )
    config_parser.add_argument(
        '--force', action='store_true',
        help='Overwrite existing config file when using --init'
    )
    config_parser.add_argument(
        '--path', dest='config_path', default=None,
        help='Path to config file (default: config/targets.yaml)'
    )

    # analyze subcommand
    analyze_parser = subparsers.add_parser(
        'analyze', help='Run all analyzers and persist results to analytics.db'
    )
    analyze_parser.add_argument(
        '--force', action='store_true',
        help='Recalculate everything even if no new imports'
    )
    analyze_parser.add_argument(
        '--type', choices=['cash', 'tournament', 'all'],
        default='all', help='Type of analysis to run (default: all)'
    )
    analyze_parser.add_argument(
        '--analytics-db', dest='analytics_db', default='analytics.db',
        help='Path to analytics database (default: analytics.db)'
    )

    # serve subcommand
    serve_parser = subparsers.add_parser(
        'serve', help='Start web UI server (Flask)'
    )
    serve_parser.add_argument(
        '--port', type=int, default=5000,
        help='Port to run the server on (default: 5000)'
    )
    serve_parser.add_argument(
        '--analytics-db', dest='analytics_db', default='analytics.db',
        help='Path to analytics database (default: analytics.db)'
    )
    serve_parser.add_argument(
        '--debug', action='store_true',
        help='Enable Flask debug mode (hot reload)'
    )
    serve_parser.add_argument(
        '--no-browser', action='store_true',
        help='Do not auto-open the browser'
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == 'import':
        cmd_import(args)
    elif args.command == 'report':
        cmd_report(args)
    elif args.command == 'stats':
        cmd_stats(args)
    elif args.command == 'config':
        cmd_config(args)
    elif args.command == 'analyze':
        cmd_analyze(args)
    elif args.command == 'serve':
        cmd_serve(args)


if __name__ == '__main__':
    main()
