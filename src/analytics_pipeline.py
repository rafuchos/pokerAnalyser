"""Analytics pipeline – runs all analyzers and persists results to analytics.db.

This module orchestrates:
1. Running CashAnalyzer + TournamentAnalyzer + EVAnalyzer + LeakFinder + TiltAnalyzer
2. Persisting every result to the analytics.db SQLite database
3. Tracking metadata (last run timestamp, source data hash) for incremental updates
"""

import hashlib
import json
import sqlite3
from datetime import datetime

from src.db.analytics_schema import init_analytics_db
from src.db.analytics_repository import AnalyticsRepository
from src.db.repository import Repository


def _compute_source_hash(repo: Repository, year: str) -> str:
    """Compute a hash of the source data to detect changes since last run."""
    cash_count = repo.get_hands_count()
    tourn_count = repo.get_tournaments_count()
    files_count = repo.get_imported_files_count()
    token = f"{cash_count}:{tourn_count}:{files_count}:{year}"
    return hashlib.md5(token.encode()).hexdigest()


def _safe_json(obj):
    """Make an object JSON-serializable (convert non-serializable to str)."""
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def _persist_cash_analysis(analytics: AnalyticsRepository,
                           repo: Repository, year: str) -> bool:
    """Run all cash analyzers and persist to analytics.db.

    Returns True if data was processed, False if no data available.
    """
    from src.analyzers.cash import CashAnalyzer
    from src.analyzers.ev import EVAnalyzer
    from src.analyzers.leak_finder import LeakFinder

    game_type = 'cash'

    if repo.get_hands_count() == 0:
        return False

    cash = CashAnalyzer(repo, year=year)
    ev = EVAnalyzer(repo, year=year)

    # ── Global Stats (summary + preflop + postflop) ───────────────
    summary = cash.get_summary()
    analytics.insert_global_stat(game_type, 'summary', stat_json=summary)

    preflop = cash.get_preflop_stats()
    analytics.insert_global_stat(
        game_type, 'preflop_overall',
        stat_json=preflop.get('overall'),
    )
    for day_key, day_data in (preflop.get('by_day') or {}).items():
        analytics.insert_daily_stat(
            game_type, day_key, 'preflop', stat_json=day_data,
        )

    postflop = cash.get_postflop_stats()
    analytics.insert_global_stat(
        game_type, 'postflop_overall',
        stat_json=postflop.get('overall'),
    )
    if postflop.get('by_street'):
        analytics.insert_global_stat(
            game_type, 'postflop_by_street',
            stat_json=postflop.get('by_street'),
        )
    if postflop.get('by_week'):
        analytics.insert_global_stat(
            game_type, 'postflop_by_week',
            stat_json=postflop.get('by_week'),
        )

    # ── Session Stats ─────────────────────────────────────────────
    try:
        daily_reports = cash.get_daily_reports_with_sessions(ev_analyzer=ev)
        for report in daily_reports:
            day = report.get('date', '')
            analytics.insert_daily_stat(
                game_type, day, 'daily_report',
                stat_json=_safe_json(report),
            )
            for i, sess in enumerate(report.get('sessions') or []):
                sess_key = f"{day}s{i + 1}"
                analytics.insert_session_stat(
                    game_type, sess_key, 'session_detail',
                    stat_json=_safe_json(sess),
                )
    except Exception:
        pass

    # ── Positional Stats ──────────────────────────────────────────
    positional = cash.get_positional_stats()
    for pos, pos_data in (positional.get('by_position') or {}).items():
        analytics.insert_positional_stat(
            game_type, pos, 'stats', stat_json=pos_data,
        )
    if positional.get('radar'):
        analytics.insert_global_stat(
            game_type, 'positional_radar',
            stat_json=positional.get('radar'),
        )
    if positional.get('blinds_defense'):
        analytics.insert_global_stat(
            game_type, 'positional_blinds_defense',
            stat_json=positional.get('blinds_defense'),
        )
    if positional.get('ats_by_pos'):
        analytics.insert_global_stat(
            game_type, 'positional_ats_by_pos',
            stat_json=positional.get('ats_by_pos'),
        )
    if positional.get('comparison'):
        analytics.insert_global_stat(
            game_type, 'positional_comparison',
            stat_json=positional.get('comparison'),
        )

    # ── Stack Depth Stats ─────────────────────────────────────────
    stack_depth = cash.get_stack_depth_stats()
    for tier, tier_data in (stack_depth.get('by_tier') or {}).items():
        analytics.insert_stack_depth_stat(
            game_type, tier, 'stats', stat_json=tier_data,
        )
    if stack_depth.get('by_position_tier'):
        analytics.insert_global_stat(
            game_type, 'stack_depth_cross_table',
            stat_json=stack_depth.get('by_position_tier'),
        )

    # ── Leak Analysis ─────────────────────────────────────────────
    leak_finder = LeakFinder(cash, repo, year=year)
    leak_result = leak_finder.find_leaks()
    for leak in leak_result.get('leaks', []):
        analytics.insert_leak(
            game_type,
            leak_name=leak['name'],
            category=leak['category'],
            stat_name=leak['stat_name'],
            current_value=leak['current_value'],
            healthy_low=leak['healthy_low'],
            healthy_high=leak['healthy_high'],
            cost_bb100=leak['cost_bb100'],
            direction=leak['direction'],
            suggestion=leak['suggestion'],
            position=leak.get('position'),
        )
    analytics.insert_global_stat(
        game_type, 'health_score',
        stat_value=leak_result.get('health_score', 0),
    )

    # ── Tilt Analysis ─────────────────────────────────────────────
    tilt = cash.get_tilt_analysis()
    for key in ('session_tilt', 'hourly', 'duration', 'post_bad_beat', 'recommendation'):
        if key in tilt:
            analytics.insert_tilt_analysis(
                game_type, key, _safe_json(tilt[key]) or {},
            )
    if tilt.get('diagnostics'):
        analytics.insert_tilt_analysis(
            game_type, 'diagnostics',
            {'messages': tilt['diagnostics']},
        )

    # ── EV Analysis ───────────────────────────────────────────────
    import sys
    print('  [cash] EV analysis (Monte Carlo, may take a few minutes)...', end='', flush=True)
    try:
        ev_data = ev.get_ev_analysis()
        analytics.insert_ev_analysis(game_type, 'allin_ev', _safe_json(ev_data))
        print(' done', flush=True)
    except Exception:
        print(' skipped (error)', flush=True)

    try:
        decision_ev = ev.get_decision_ev_analysis()
        analytics.insert_ev_analysis(
            game_type, 'decision_ev', _safe_json(decision_ev),
        )
    except Exception:
        pass

    # ── Bet Sizing ────────────────────────────────────────────────
    sizing = cash.get_bet_sizing_analysis()
    analytics.insert_bet_sizing(game_type, 'overall', _safe_json(sizing))

    # ── Hand Matrix ───────────────────────────────────────────────
    matrix = cash.get_hand_matrix()
    for pos, pos_data in (matrix.get('by_position') or {}).items():
        for combo, combo_data in pos_data.items():
            if isinstance(combo_data, dict):
                analytics.insert_hand_matrix_entry(
                    game_type, pos, combo,
                    dealt=combo_data.get('dealt', 0),
                    played=combo_data.get('played', 0),
                    total_net=combo_data.get('bb_net', combo_data.get('net', 0)),
                    bb100=combo_data.get('win_rate', combo_data.get('bb100', 0)),
                    action_breakdown=combo_data.get('action_breakdown'),
                )

    # ── Red Line / Blue Line ──────────────────────────────────────
    redline = cash.get_redline_blueline()
    analytics.insert_redline_blueline(game_type, 'overall', _safe_json(redline))

    analytics.commit()
    return True


def _persist_tournament_analysis(analytics: AnalyticsRepository,
                                 repo: Repository, year: str) -> bool:
    """Run all tournament analyzers and persist to analytics.db.

    Returns True if data was processed, False if no data available.
    """
    from src.analyzers.tournament import TournamentAnalyzer
    from src.analyzers.ev import EVAnalyzer
    from src.analyzers.leak_finder import LeakFinder

    game_type = 'tournament'

    if repo.get_tournaments_count() == 0:
        return False

    tourn = TournamentAnalyzer(repo, year=year)
    ev = EVAnalyzer(repo, year=year)

    # ── Global Stats (summary + preflop + postflop) ───────────────
    summary = tourn.get_summary()
    analytics.insert_global_stat(game_type, 'summary', stat_json=summary)

    preflop = tourn.get_preflop_stats()
    analytics.insert_global_stat(
        game_type, 'preflop_overall',
        stat_json=preflop.get('overall'),
    )

    postflop = tourn.get_postflop_stats()
    analytics.insert_global_stat(
        game_type, 'postflop_overall',
        stat_json=postflop.get('overall'),
    )
    if postflop.get('by_street'):
        analytics.insert_global_stat(
            game_type, 'postflop_by_street',
            stat_json=postflop.get('by_street'),
        )
    if postflop.get('by_week'):
        analytics.insert_global_stat(
            game_type, 'postflop_by_week',
            stat_json=postflop.get('by_week'),
        )

    # ── Session / Daily Stats ─────────────────────────────────────
    try:
        daily_reports = tourn.get_daily_reports()
        for report in daily_reports:
            day = report.get('date', '')
            analytics.insert_daily_stat(
                game_type, day, 'daily_report',
                stat_json=_safe_json(report),
            )
    except Exception:
        pass

    # ── Positional Stats ──────────────────────────────────────────
    positional = tourn.get_positional_stats()
    for pos, pos_data in (positional.get('by_position') or {}).items():
        analytics.insert_positional_stat(
            game_type, pos, 'stats', stat_json=pos_data,
        )
    if positional.get('radar'):
        analytics.insert_global_stat(
            game_type, 'positional_radar',
            stat_json=positional.get('radar'),
        )
    if positional.get('blinds_defense'):
        analytics.insert_global_stat(
            game_type, 'positional_blinds_defense',
            stat_json=positional.get('blinds_defense'),
        )
    if positional.get('ats_by_pos'):
        analytics.insert_global_stat(
            game_type, 'positional_ats_by_pos',
            stat_json=positional.get('ats_by_pos'),
        )
    if positional.get('comparison'):
        analytics.insert_global_stat(
            game_type, 'positional_comparison',
            stat_json=positional.get('comparison'),
        )

    # ── Stack Depth Stats ─────────────────────────────────────────
    stack_depth = tourn.get_stack_depth_stats()
    for tier, tier_data in (stack_depth.get('by_tier') or {}).items():
        analytics.insert_stack_depth_stat(
            game_type, tier, 'stats', stat_json=tier_data,
        )
    if stack_depth.get('by_position_tier'):
        analytics.insert_global_stat(
            game_type, 'stack_depth_cross_table',
            stat_json=stack_depth.get('by_position_tier'),
        )

    # ── Leak Analysis ─────────────────────────────────────────────
    leak_finder = LeakFinder(tourn, repo, year=year)
    leak_result = leak_finder.find_leaks()
    for leak in leak_result.get('leaks', []):
        analytics.insert_leak(
            game_type,
            leak_name=leak['name'],
            category=leak['category'],
            stat_name=leak['stat_name'],
            current_value=leak['current_value'],
            healthy_low=leak['healthy_low'],
            healthy_high=leak['healthy_high'],
            cost_bb100=leak['cost_bb100'],
            direction=leak['direction'],
            suggestion=leak['suggestion'],
            position=leak.get('position'),
        )
    analytics.insert_global_stat(
        game_type, 'health_score',
        stat_value=leak_result.get('health_score', 0),
    )

    # ── Tilt Analysis ─────────────────────────────────────────────
    tilt = tourn.get_tilt_analysis()
    for key in ('session_tilt', 'hourly', 'duration', 'post_bad_beat', 'recommendation'):
        if key in tilt:
            analytics.insert_tilt_analysis(
                game_type, key, _safe_json(tilt[key]) or {},
            )
    if tilt.get('diagnostics'):
        analytics.insert_tilt_analysis(
            game_type, 'diagnostics',
            {'messages': tilt['diagnostics']},
        )

    # ── EV Analysis ───────────────────────────────────────────────
    print('  [tournament] EV analysis (Monte Carlo, may take a few minutes)...', end='', flush=True)
    try:
        ev_data = tourn.get_ev_analysis()
        analytics.insert_ev_analysis(game_type, 'allin_ev', _safe_json(ev_data))
        print(' done', flush=True)
    except Exception:
        print(' skipped (error)', flush=True)

    try:
        decision_ev = ev.get_tournament_decision_ev_analysis()
        analytics.insert_ev_analysis(
            game_type, 'decision_ev', _safe_json(decision_ev),
        )
    except Exception:
        pass

    # ── Bet Sizing ────────────────────────────────────────────────
    sizing = tourn.get_bet_sizing_analysis()
    analytics.insert_bet_sizing(game_type, 'overall', _safe_json(sizing))

    # ── Hand Matrix ───────────────────────────────────────────────
    matrix = tourn.get_hand_matrix()
    for pos, pos_data in (matrix.get('by_position') or {}).items():
        for combo, combo_data in pos_data.items():
            if isinstance(combo_data, dict):
                analytics.insert_hand_matrix_entry(
                    game_type, pos, combo,
                    dealt=combo_data.get('dealt', 0),
                    played=combo_data.get('played', 0),
                    total_net=combo_data.get('bb_net', combo_data.get('net', 0)),
                    bb100=combo_data.get('win_rate', combo_data.get('bb100', 0)),
                    action_breakdown=combo_data.get('action_breakdown'),
                )

    # ── Red Line / Blue Line ──────────────────────────────────────
    redline = tourn.get_redline_blueline()
    analytics.insert_redline_blueline(game_type, 'overall', _safe_json(redline))

    # ── Satellite / Spin Analysis ──────────────────────────────────
    try:
        from src.analyzers.spin import SpinAnalyzer
        spin = SpinAnalyzer(repo)
        sat_analysis = spin.get_satellite_analysis()
        if sat_analysis:
            analytics.insert_global_stat(
                game_type, 'satellite_analysis',
                stat_json=_safe_json(sat_analysis),
            )
    except Exception:
        pass

    analytics.commit()
    return True


def _persist_lesson_stats(analytics: AnalyticsRepository,
                          repo: Repository):
    """Aggregate hand_lessons data per lesson per game_type and persist."""
    # Clear existing lesson stats for both game types
    try:
        analytics.conn.execute("DELETE FROM lesson_stats")
    except Exception:
        pass

    lessons = repo.get_lessons()
    if not lessons:
        return

    # Query all hand_lessons joined with hands for game_type
    rows = repo.conn.execute("""
        SELECT hl.lesson_id, hl.street, hl.executed_correctly,
               hl.confidence, h.game_type, h.date, h.net, h.blinds_bb
        FROM hand_lessons hl
        JOIN hands h ON hl.hand_id = h.hand_id
        ORDER BY hl.lesson_id
    """).fetchall()

    # Build per-lesson, per-game_type stats
    # key: (lesson_id, game_type)
    stats = {}
    for r in rows:
        lid = r['lesson_id']
        gt = r['game_type'] or 'cash'
        key = (lid, gt)
        if key not in stats:
            stats[key] = {
                'total': 0, 'correct': 0, 'incorrect': 0, 'unknown': 0,
                'by_street': {}, 'dates': [],
            }
        s = stats[key]
        s['total'] += 1
        ec = r['executed_correctly']
        if ec == 1:
            s['correct'] += 1
        elif ec == 0:
            s['incorrect'] += 1
        else:
            s['unknown'] += 1

        street = r['street'] or 'unknown'
        if street not in s['by_street']:
            s['by_street'][street] = {'total': 0, 'correct': 0, 'incorrect': 0}
        bs = s['by_street'][street]
        bs['total'] += 1
        if ec == 1:
            bs['correct'] += 1
        elif ec == 0:
            bs['incorrect'] += 1

        if r['date']:
            s['dates'].append(str(r['date'])[:10])

    # Build lesson catalog lookup
    lesson_map = {l['lesson_id']: l for l in lessons}

    for (lid, gt), s in stats.items():
        lesson = lesson_map.get(lid, {})
        total_evaluated = s['correct'] + s['incorrect']
        accuracy = round(s['correct'] / total_evaluated * 100, 1) if total_evaluated > 0 else None
        error_rate = round(s['incorrect'] / total_evaluated * 100, 1) if total_evaluated > 0 else None

        stat_data = {
            'lesson_id': lid,
            'title': lesson.get('title', ''),
            'category': lesson.get('category', ''),
            'subcategory': lesson.get('subcategory', ''),
            'description': lesson.get('description', ''),
            'total_hands': s['total'],
            'correct': s['correct'],
            'incorrect': s['incorrect'],
            'unknown': s['unknown'],
            'accuracy': accuracy,
            'error_rate': error_rate,
            'by_street': s['by_street'],
        }

        # Mastery classification
        if total_evaluated >= 20 and accuracy is not None and accuracy >= 80:
            stat_data['mastery'] = 'mastered'
        elif total_evaluated >= 10 and accuracy is not None and accuracy >= 60:
            stat_data['mastery'] = 'learning'
        elif total_evaluated > 0:
            stat_data['mastery'] = 'needs_work'
        else:
            stat_data['mastery'] = 'no_data'

        analytics.insert_lesson_stat(gt, lid, stat_data)

    # Also persist global lesson summary per game_type
    for gt in ('cash', 'tournament'):
        gt_stats = {k: v for k, v in stats.items() if k[1] == gt}
        if not gt_stats:
            continue
        total_hands = sum(v['total'] for v in gt_stats.values())
        total_correct = sum(v['correct'] for v in gt_stats.values())
        total_incorrect = sum(v['incorrect'] for v in gt_stats.values())
        total_evaluated = total_correct + total_incorrect
        global_accuracy = round(total_correct / total_evaluated * 100, 1) if total_evaluated > 0 else None

        mastered = 0
        learning = 0
        needs_work = 0
        for (lid, _), s in gt_stats.items():
            te = s['correct'] + s['incorrect']
            acc = round(s['correct'] / te * 100, 1) if te > 0 else None
            if te >= 20 and acc is not None and acc >= 80:
                mastered += 1
            elif te >= 10 and acc is not None and acc >= 60:
                learning += 1
            elif te > 0:
                needs_work += 1

        # Category breakdown
        by_category = {}
        for (lid, _), s in gt_stats.items():
            lesson = lesson_map.get(lid, {})
            cat = lesson.get('category', 'Other')
            if cat not in by_category:
                by_category[cat] = {'total': 0, 'correct': 0, 'incorrect': 0}
            by_category[cat]['total'] += s['total']
            by_category[cat]['correct'] += s['correct']
            by_category[cat]['incorrect'] += s['incorrect']
        for cat_data in by_category.values():
            te = cat_data['correct'] + cat_data['incorrect']
            cat_data['accuracy'] = round(cat_data['correct'] / te * 100, 1) if te > 0 else None

        summary = {
            'total_lessons_with_data': len(gt_stats),
            'total_lessons': len(lessons),
            'total_hands': total_hands,
            'total_correct': total_correct,
            'total_incorrect': total_incorrect,
            'global_accuracy': global_accuracy,
            'mastered': mastered,
            'learning': learning,
            'needs_work': needs_work,
            'by_category': by_category,
        }
        analytics.insert_global_stat(gt, 'lesson_summary', stat_json=summary)

    analytics.commit()


def run_analysis(poker_db_path: str = 'poker.db',
                 analytics_db_path: str = 'analytics.db',
                 force: bool = False,
                 analysis_type: str = 'all',
                 year: str = '2026') -> dict:
    """Run the full analysis pipeline.

    Args:
        poker_db_path: Path to the source poker database.
        analytics_db_path: Path to the analytics database (created if missing).
        force: If True, recalculate everything regardless of changes.
        analysis_type: 'cash', 'tournament', or 'all'.
        year: Year filter for analyzers.

    Returns:
        dict with keys: cash_processed (bool), tournament_processed (bool),
        skipped (bool), reason (str).
    """
    # Open source DB
    source_conn = sqlite3.connect(poker_db_path)
    source_conn.row_factory = sqlite3.Row
    from src.db.schema import init_db
    init_db(source_conn)
    repo = Repository(source_conn)

    # Open / create analytics DB
    analytics_conn = sqlite3.connect(analytics_db_path)
    analytics_conn.row_factory = sqlite3.Row
    init_analytics_db(analytics_conn)
    analytics = AnalyticsRepository(analytics_conn)

    result = {
        'cash_processed': False,
        'tournament_processed': False,
        'skipped': False,
        'reason': '',
    }

    # Check if re-processing is needed
    source_hash = _compute_source_hash(repo, year)
    last_hash = analytics.get_meta('source_hash')

    if not force and last_hash == source_hash:
        result['skipped'] = True
        result['reason'] = 'No new imports detected (use --force to recalculate)'
        source_conn.close()
        analytics_conn.close()
        return result

    # Process cash
    if analysis_type in ('cash', 'all'):
        analytics.clear_game_type('cash')
        result['cash_processed'] = _persist_cash_analysis(
            analytics, repo, year) or False

    # Process tournament
    if analysis_type in ('tournament', 'all'):
        analytics.clear_game_type('tournament')
        result['tournament_processed'] = _persist_tournament_analysis(
            analytics, repo, year) or False

    # Lesson Classification + Lesson Stats
    try:
        from src.analyzers.lesson_classifier import LessonClassifier
        classifier = LessonClassifier(repo)
        classify_result = classifier.classify_all()
        result['classify_links'] = classify_result.get('total_links', 0)
        result['classify_lessons'] = classify_result.get('lessons_matched', 0)

        # Persist lesson performance stats
        _persist_lesson_stats(analytics, repo)
    except Exception:
        pass

    # Update metadata
    analytics.set_meta('source_hash', source_hash)
    analytics.set_meta('last_run', datetime.now().isoformat())
    analytics.set_meta('analysis_type', analysis_type)

    source_conn.close()
    analytics_conn.close()

    return result
