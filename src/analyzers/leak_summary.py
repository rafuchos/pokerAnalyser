"""Leak Summary Analyzer – consolidates all leak analyses into a session-grade report.

Provides:
- Grade mapping from health_score (A+ to F)
- Top priority leaks (highest cost)
- Leaks grouped by category
- Consolidated summary for overview display
"""


def grade_from_score(score: int) -> str:
    """Map a 0-100 health score to a letter grade (A+ to F)."""
    if score >= 95:
        return 'A+'
    if score >= 90:
        return 'A'
    if score >= 85:
        return 'A-'
    if score >= 80:
        return 'B+'
    if score >= 75:
        return 'B'
    if score >= 70:
        return 'B-'
    if score >= 65:
        return 'C+'
    if score >= 60:
        return 'C'
    if score >= 55:
        return 'C-'
    if score >= 50:
        return 'D+'
    if score >= 45:
        return 'D'
    if score >= 40:
        return 'D-'
    return 'F'


def grade_color(grade: str) -> str:
    """Return a CSS color class for the grade."""
    if grade.startswith('A'):
        return 'good'
    if grade.startswith('B'):
        return 'good'
    if grade.startswith('C'):
        return 'warning'
    if grade.startswith('D'):
        return 'warning'
    return 'danger'


def build_leak_summary(health_score: int, leaks: list) -> dict:
    """Build a consolidated leak summary from health_score and leak list.

    Args:
        health_score: 0-100 health score from LeakFinder.
        leaks: List of leak dicts (from analytics DB or LeakFinder).

    Returns:
        dict with keys:
            grade: str (A+ to F)
            grade_color: str (good/warning/danger)
            health_score: int
            total_leaks: int
            total_cost: float (sum of cost_bb100)
            top_leaks: list (top 3 by cost_bb100)
            by_category: dict[str, list] (leaks grouped by category)
            categories: list[dict] (category name, count, total_cost)
    """
    score = max(0, min(100, int(health_score or 0)))
    grade = grade_from_score(score)

    sorted_leaks = sorted(
        leaks or [],
        key=lambda l: l.get('cost_bb100', 0) or 0,
        reverse=True,
    )

    total_cost = sum(l.get('cost_bb100', 0) or 0 for l in sorted_leaks)

    # Group by category
    by_category: dict[str, list] = {}
    for leak in sorted_leaks:
        cat = leak.get('category', 'other')
        by_category.setdefault(cat, []).append(leak)

    categories = []
    for cat_name in sorted(by_category.keys()):
        cat_leaks = by_category[cat_name]
        categories.append({
            'name': cat_name,
            'count': len(cat_leaks),
            'total_cost': sum(l.get('cost_bb100', 0) or 0 for l in cat_leaks),
        })

    return {
        'grade': grade,
        'grade_color': grade_color(grade),
        'health_score': score,
        'total_leaks': len(sorted_leaks),
        'total_cost': round(total_cost, 2),
        'top_leaks': sorted_leaks[:3],
        'by_category': by_category,
        'categories': categories,
    }
