"""Leak Finder module.

Automatically detects leaks by comparing player stats against healthy benchmarks,
estimates cost in bb/100, and generates prioritized study spots.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.analyzers.cash import CashAnalyzer
from src.db.repository import Repository


@dataclass
class Leak:
    """Individual leak descriptor."""
    name: str
    category: str          # 'preflop', 'postflop', 'positional', 'sizing'
    stat_name: str         # e.g. 'vpip', 'af', 'cbet'
    current_value: float
    healthy_low: float
    healthy_high: float
    cost_bb100: float      # estimated cost in bb/100
    direction: str         # 'too_high' or 'too_low'
    suggestion: str        # concrete study action
    position: str = ''     # only for positional leaks


class LeakFinder:
    """Detect leaks, estimate costs, and generate study spots."""

    # Weights: how many bb/100 a 1-percentage-point deviation costs per stat
    PREFLOP_WEIGHTS = {
        'vpip': 0.15,
        'pfr': 0.18,
        'three_bet': 0.12,
        'fold_to_3bet': 0.10,
        'ats': 0.08,
    }

    POSTFLOP_WEIGHTS = {
        'af': 0.40,       # per-unit deviation (AF is ratio, not pct)
        'wtsd': 0.12,
        'wsd': 0.10,
        'cbet': 0.10,
        'fold_to_cbet': 0.08,
        'check_raise': 0.06,
    }

    POSITIONAL_WEIGHTS = {
        'vpip': 0.12,
        'pfr': 0.14,
    }

    # Min hands for leak detection
    MIN_HANDS_OVERALL = 50
    MIN_HANDS_POSITION = 20

    def __init__(self, analyzer: CashAnalyzer, repo: Repository, year: str = '2026'):
        self.analyzer = analyzer
        self.repo = repo
        self.year = year

    def find_leaks(self) -> dict:
        """Run full leak analysis.

        Returns dict with:
        - leaks: list of Leak objects sorted by cost (highest first)
        - top5: top 5 leaks with priority badges
        - study_spots: list of concrete study actions
        - health_score: 0-100 overall health score
        - period_comparison: last 30 days vs overall stats comparison
        """
        preflop_stats = self.analyzer.get_preflop_stats()
        postflop_stats = self.analyzer.get_postflop_stats()
        positional_stats = self.analyzer.get_positional_stats()

        overall_preflop = preflop_stats.get('overall', {})
        overall_postflop = postflop_stats.get('overall', {})
        by_position = positional_stats.get('by_position', {})

        all_leaks = []

        # Detect preflop leaks
        if overall_preflop.get('total_hands', 0) >= self.MIN_HANDS_OVERALL:
            all_leaks.extend(self._detect_preflop_leaks(overall_preflop))

        # Detect postflop leaks
        if overall_postflop.get('saw_flop_hands', 0) >= self.MIN_HANDS_OVERALL:
            all_leaks.extend(self._detect_postflop_leaks(overall_postflop))

        # Detect positional leaks
        all_leaks.extend(self._detect_positional_leaks(by_position))

        # Sort by cost (highest first)
        all_leaks.sort(key=lambda x: x.cost_bb100, reverse=True)

        # Top 5 with priority badges
        top5 = all_leaks[:5]

        # Generate study spots
        study_spots = self._generate_study_spots(all_leaks)

        # Calculate health score
        health_score = self._calculate_health_score(all_leaks)

        # Period comparison
        period_comparison = self._compare_periods(overall_preflop, overall_postflop)

        return {
            'leaks': [self._leak_to_dict(l) for l in all_leaks],
            'top5': [self._leak_to_dict(l) for l in top5],
            'study_spots': study_spots,
            'health_score': health_score,
            'period_comparison': period_comparison,
            'total_leaks': len(all_leaks),
        }

    @staticmethod
    def _leak_to_dict(leak: Leak) -> dict:
        """Convert a Leak dataclass to a dict for serialization."""
        return {
            'name': leak.name,
            'category': leak.category,
            'stat_name': leak.stat_name,
            'current_value': leak.current_value,
            'healthy_low': leak.healthy_low,
            'healthy_high': leak.healthy_high,
            'cost_bb100': leak.cost_bb100,
            'direction': leak.direction,
            'suggestion': leak.suggestion,
            'position': leak.position,
        }

    def _detect_preflop_leaks(self, overall: dict) -> list[Leak]:
        """Detect preflop leaks by comparing stats against healthy ranges."""
        leaks = []
        for stat_name, weight in self.PREFLOP_WEIGHTS.items():
            value = overall.get(stat_name, 0)
            healthy = self.analyzer._healthy_ranges.get(stat_name)
            if not healthy:
                continue

            low, high = healthy
            leak = self._check_deviation(
                stat_name, value, low, high, weight, 'preflop',
            )
            if leak:
                leaks.append(leak)
        return leaks

    def _detect_postflop_leaks(self, overall: dict) -> list[Leak]:
        """Detect postflop leaks by comparing stats against healthy ranges."""
        leaks = []
        for stat_name, weight in self.POSTFLOP_WEIGHTS.items():
            value = overall.get(stat_name, 0)
            healthy = self.analyzer._postflop_healthy_ranges.get(stat_name)
            if not healthy:
                continue

            low, high = healthy
            leak = self._check_deviation(
                stat_name, value, low, high, weight, 'postflop',
            )
            if leak:
                leaks.append(leak)
        return leaks

    def _detect_positional_leaks(self, by_position: dict) -> list[Leak]:
        """Detect per-position leaks using position-specific ranges."""
        leaks = []
        for pos, stats in by_position.items():
            if stats.get('total_hands', 0) < self.MIN_HANDS_POSITION:
                continue

            # VPIP per position
            vpip_healthy = self.analyzer._pos_vpip_healthy.get(pos)
            if vpip_healthy:
                value = stats.get('vpip', 0)
                leak = self._check_deviation(
                    'vpip', value, vpip_healthy[0], vpip_healthy[1],
                    self.POSITIONAL_WEIGHTS['vpip'], 'positional',
                    position=pos,
                )
                if leak:
                    leaks.append(leak)

            # PFR per position
            pfr_healthy = self.analyzer._pos_pfr_healthy.get(pos)
            if pfr_healthy:
                value = stats.get('pfr', 0)
                leak = self._check_deviation(
                    'pfr', value, pfr_healthy[0], pfr_healthy[1],
                    self.POSITIONAL_WEIGHTS['pfr'], 'positional',
                    position=pos,
                )
                if leak:
                    leaks.append(leak)

        return leaks

    def _check_deviation(self, stat_name: str, value: float,
                         healthy_low: float, healthy_high: float,
                         weight: float, category: str,
                         position: str = '') -> Leak | None:
        """Check if a stat deviates from healthy range and compute cost.

        Returns a Leak if deviation exists, None otherwise.
        """
        if healthy_low <= value <= healthy_high:
            return None

        if value < healthy_low:
            deviation = healthy_low - value
            direction = 'too_low'
        else:
            deviation = value - healthy_high
            direction = 'too_high'

        cost_bb100 = round(deviation * weight, 2)
        name = self._leak_name(stat_name, direction, category, position)
        suggestion = self._leak_suggestion(stat_name, direction, category, position)

        return Leak(
            name=name,
            category=category,
            stat_name=stat_name,
            current_value=round(value, 1),
            healthy_low=healthy_low,
            healthy_high=healthy_high,
            cost_bb100=cost_bb100,
            direction=direction,
            suggestion=suggestion,
            position=position,
        )

    @staticmethod
    def _leak_name(stat_name: str, direction: str, category: str,
                   position: str = '') -> str:
        """Generate human-readable leak name in Portuguese."""
        stat_labels = {
            'vpip': 'VPIP', 'pfr': 'PFR', 'three_bet': '3-Bet',
            'fold_to_3bet': 'Fold to 3-Bet', 'ats': 'ATS',
            'af': 'AF', 'wtsd': 'WTSD', 'wsd': 'W$SD',
            'cbet': 'CBet', 'fold_to_cbet': 'Fold to CBet',
            'check_raise': 'Check-Raise',
        }
        label = stat_labels.get(stat_name, stat_name)
        dir_label = 'muito alto' if direction == 'too_high' else 'muito baixo'
        pos_suffix = f' no {position}' if position else ''

        return f'{label} {dir_label}{pos_suffix}'

    @staticmethod
    def _leak_suggestion(stat_name: str, direction: str, category: str,
                         position: str = '') -> str:
        """Generate concrete study suggestion for a leak."""
        pos_ctx = f' no {position}' if position else ''

        suggestions = {
            ('vpip', 'too_high'): f'Reduza range de abertura{pos_ctx}: revise hands marginais que está jogando e corte as mais fracas',
            ('vpip', 'too_low'): f'Amplie range de abertura{pos_ctx}: estude ranges de open-raise por posição e adicione mãos com bom playability',
            ('pfr', 'too_high'): f'Reduza frequência de raise{pos_ctx}: identifique spots onde limp ou call seria mais lucrativo',
            ('pfr', 'too_low'): f'Aumente agressividade preflop{pos_ctx}: substitua calls por raises com mãos fortes e semi-bluffs',
            ('three_bet', 'too_high'): 'Reduza frequência de 3-bet: polarize mais entre value e bluffs, remova 3-bets marginais',
            ('three_bet', 'too_low'): 'Aumente frequência de 3-bet: adicione mais 3-bets como bluff com suited connectors e Ax suited',
            ('fold_to_3bet', 'too_high'): 'Defenda mais contra 3-bets: amplie range de call e 4-bet bluff contra 3-bets frequentes',
            ('fold_to_3bet', 'too_low'): 'Folde mais contra 3-bets: remova calls marginais e respeite ranges de 3-bet mais tight',
            ('ats', 'too_high'): 'Reduza frequência de steal: opponents estão ajustando, selecione spots com menos resistência',
            ('ats', 'too_low'): 'Aumente steals em posição de steal: abra mais ranges no CO/BTN/SB quando folda até você',
            ('af', 'too_high'): 'Reduza agressividade postflop: adicione mais checks e calls ao range, evite bluffs excessivos',
            ('af', 'too_low'): 'Aumente agressividade postflop: aposte e raise mais com value hands e bluffs equilibrados',
            ('wtsd', 'too_high'): 'Vá ao showdown com menos frequência: folde mais em rivers com mãos fracas que não tem equity suficiente',
            ('wtsd', 'too_low'): 'Vá ao showdown mais vezes: defenda com mãos que tem equity suficiente, não folde demais a bets',
            ('wsd', 'too_high'): 'W$SD alto sugere jogo muito tight postflop: considere bluffar mais para equilibrar',
            ('wsd', 'too_low'): 'Melhore seleção de mãos levadas ao showdown: só vá ao showdown com mãos que vencem frequentemente',
            ('cbet', 'too_high'): 'Reduza frequência de c-bet: check mais em boards que não favorecem seu range',
            ('cbet', 'too_low'): 'Aumente c-bets: aposte mais como PFA em boards favoráveis ao seu range',
            ('fold_to_cbet', 'too_high'): 'Defenda mais contra c-bets: adicione floating e check-raises ao range de defesa',
            ('fold_to_cbet', 'too_low'): 'Folde mais contra c-bets: evite chamar com draws fracos sem implied odds',
            ('check_raise', 'too_high'): 'Reduza check-raises: selecione melhor os spots, check-raise apenas com value forte e bluffs com equity',
            ('check_raise', 'too_low'): 'Aumente check-raises: adicione check-raises como bluff com draws e como value com mãos fortes',
        }

        key = (stat_name, direction)
        suggestion = suggestions.get(key)
        if suggestion:
            return suggestion

        dir_label = 'reduzir' if direction == 'too_high' else 'aumentar'
        return f'Estudar como {dir_label} {stat_name}{pos_ctx}'

    def _generate_study_spots(self, leaks: list[Leak]) -> list[dict]:
        """Generate concrete study spots from detected leaks."""
        spots = []
        seen = set()

        for leak in leaks:
            spot = self._study_spot_for_leak(leak)
            # Deduplicate by spot title
            if spot['title'] not in seen:
                seen.add(spot['title'])
                spots.append(spot)

        return spots[:10]  # Max 10 study spots

    @staticmethod
    def _study_spot_for_leak(leak: Leak) -> dict:
        """Generate a specific study spot for a leak."""
        study_actions = {
            ('preflop', 'vpip', 'too_high'): {
                'title': 'Estudar ranges de abertura preflop',
                'action': 'Revise a tabela de open-raise ranges por posição. Identifique mãos marginais que está jogando e corte-as.',
                'priority': 'alta',
            },
            ('preflop', 'vpip', 'too_low'): {
                'title': 'Ampliar ranges de abertura preflop',
                'action': 'Estude mãos com bom playability (suited connectors, small pocket pairs) para adicionar ao range.',
                'priority': 'alta',
            },
            ('preflop', 'pfr', 'too_high'): {
                'title': 'Equilibrar frequência de raise preflop',
                'action': 'Identifique spots onde limp ou call seria mais lucrativo que raise.',
                'priority': 'alta',
            },
            ('preflop', 'pfr', 'too_low'): {
                'title': 'Aumentar agressividade preflop',
                'action': 'Substitua calls por raises com mãos como ATo+, KQo, suited broadways.',
                'priority': 'alta',
            },
            ('preflop', 'three_bet', 'too_high'): {
                'title': 'Ajustar frequência de 3-bet',
                'action': 'Remova 3-bets marginais (KJo, QJo) e mantenha 3-bets polarizados.',
                'priority': 'média',
            },
            ('preflop', 'three_bet', 'too_low'): {
                'title': 'Estudar ranges de 3-bet por posição',
                'action': 'Adicione 3-bets bluff com Axs, suited connectors (87s, 76s) contra opens do CO/BTN.',
                'priority': 'média',
            },
            ('preflop', 'fold_to_3bet', 'too_high'): {
                'title': 'Estudar defesa contra 3-bet',
                'action': 'Amplie range de call vs 3-bet (pocket pairs, suited connectors) e adicione 4-bet bluffs.',
                'priority': 'média',
            },
            ('preflop', 'fold_to_3bet', 'too_low'): {
                'title': 'Estudar seleção de mãos vs 3-bet',
                'action': 'Remova calls marginais vs 3-bet e folde hands sem bom playability OOP.',
                'priority': 'média',
            },
            ('preflop', 'ats', 'too_high'): {
                'title': 'Ajustar frequência de steal',
                'action': 'Reduza steals quando blinds estão defendendo muito. Selecione spots com menos resistência.',
                'priority': 'baixa',
            },
            ('preflop', 'ats', 'too_low'): {
                'title': 'Estudar steal de blinds por posição',
                'action': 'Abra mais ranges no CO/BTN/SB quando folda até você. Use 2.5x sizing.',
                'priority': 'média',
            },
            ('postflop', 'af', 'too_high'): {
                'title': 'Equilibrar agressividade postflop',
                'action': 'Adicione mais checks ao range para proteger e evitar bluffs excessivos.',
                'priority': 'alta',
            },
            ('postflop', 'af', 'too_low'): {
                'title': 'Aumentar agressividade postflop',
                'action': 'Aposte mais com value hands e adicione bluffs equilibrados ao range de bet.',
                'priority': 'alta',
            },
            ('postflop', 'wtsd', 'too_high'): {
                'title': 'Estudar seleção de mãos no showdown',
                'action': 'Folde mais em rivers com mãos fracas. Use pot odds para calcular equity mínima.',
                'priority': 'média',
            },
            ('postflop', 'wtsd', 'too_low'): {
                'title': 'Defender mais em streets tardias',
                'action': 'Defenda com mãos que tem equity suficiente. Não folde demais a bets.',
                'priority': 'média',
            },
            ('postflop', 'wsd', 'too_high'): {
                'title': 'Equilibrar range de showdown',
                'action': 'W$SD alto pode indicar range muito tight. Considere bluffar mais.',
                'priority': 'baixa',
            },
            ('postflop', 'wsd', 'too_low'): {
                'title': 'Melhorar seleção de mãos no showdown',
                'action': 'Só vá ao showdown com mãos que vencem frequentemente. Folde mais com bluff catchers fracos.',
                'priority': 'alta',
            },
            ('postflop', 'cbet', 'too_high'): {
                'title': 'Estudar seleção de c-bet boards',
                'action': 'Check mais em boards wet/low que não favorecem seu range.',
                'priority': 'média',
            },
            ('postflop', 'cbet', 'too_low'): {
                'title': 'Aumentar frequência de c-bet',
                'action': 'Aposte como PFA em dry/high boards que favorecem seu range.',
                'priority': 'média',
            },
            ('postflop', 'fold_to_cbet', 'too_high'): {
                'title': 'Estudar defesa contra c-bet',
                'action': 'Adicione floating e check-raises ao range de defesa contra c-bets.',
                'priority': 'média',
            },
            ('postflop', 'fold_to_cbet', 'too_low'): {
                'title': 'Ajustar defesa contra c-bet',
                'action': 'Folde mais contra c-bets: evite chamar com draws fracos sem implied odds.',
                'priority': 'baixa',
            },
            ('postflop', 'check_raise', 'too_high'): {
                'title': 'Ajustar frequência de check-raise',
                'action': 'Reduza check-raises marginais, mantenha apenas com value forte e bluffs com equity.',
                'priority': 'baixa',
            },
            ('postflop', 'check_raise', 'too_low'): {
                'title': 'Estudar spots de check-raise',
                'action': 'Adicione check-raises como bluff com draws (OESD, flush draws) e como value.',
                'priority': 'média',
            },
        }

        key = (leak.category, leak.stat_name, leak.direction)
        default = {
            'title': f'Estudar {leak.stat_name} ({leak.category})',
            'action': leak.suggestion,
            'priority': 'média',
        }

        # For positional leaks, generate position-specific study spot
        if leak.category == 'positional' and leak.position:
            pos = leak.position
            stat_labels = {
                'vpip': 'VPIP', 'pfr': 'PFR',
            }
            label = stat_labels.get(leak.stat_name, leak.stat_name)
            dir_action = 'Reduza' if leak.direction == 'too_high' else 'Aumente'
            return {
                'title': f'Estudar {label} no {pos}',
                'action': f'{dir_action} {label} no {pos}: range atual ({leak.current_value:.1f}%) fora do ideal ({leak.healthy_low:.0f}-{leak.healthy_high:.0f}%).',
                'priority': 'média' if leak.cost_bb100 < 1.0 else 'alta',
            }

        return study_actions.get(key, default)

    @staticmethod
    def _calculate_health_score(leaks: list[Leak]) -> int:
        """Calculate overall health score 0-100 based on leak severity.

        Starts at 100, subtracts points proportional to each leak's cost.
        """
        if not leaks:
            return 100

        total_cost = sum(l.cost_bb100 for l in leaks)
        # Scale: each 0.5 bb/100 of total leak cost reduces score by ~5 points
        penalty = total_cost * 10
        score = max(0, min(100, round(100 - penalty)))
        return score

    def _compare_periods(self, overall_preflop: dict,
                         overall_postflop: dict) -> dict:
        """Compare stats from last 30 days vs overall.

        Returns dict with both period stats for comparison.
        """
        # Calculate date threshold (30 days ago)
        today = datetime.strptime(f'{self.year}-12-31', '%Y-%m-%d')
        try:
            # Try to get actual latest date from hands
            daily_stats = self.repo.get_cash_daily_stats(self.year)
            if daily_stats:
                latest = daily_stats[-1]['day']
                today = datetime.strptime(latest, '%Y-%m-%d')
        except (ValueError, IndexError):
            pass

        threshold = (today - timedelta(days=30)).strftime('%Y-%m-%d')

        # Get recent stats by analyzing only recent hands
        recent_preflop = self._get_recent_preflop_stats(threshold)
        recent_postflop = self._get_recent_postflop_stats(threshold)

        if not recent_preflop and not recent_postflop:
            return {}

        comparison = {'overall': {}, 'recent': {}, 'period_label': f'Últimos 30 dias (desde {threshold})'}

        # Overall stats
        for stat in ('vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats'):
            comparison['overall'][stat] = overall_preflop.get(stat, 0)
        for stat in ('af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise'):
            comparison['overall'][stat] = overall_postflop.get(stat, 0)

        # Recent stats
        if recent_preflop:
            for stat in ('vpip', 'pfr', 'three_bet', 'fold_to_3bet', 'ats'):
                comparison['recent'][stat] = recent_preflop.get(stat, 0)

        if recent_postflop:
            for stat in ('af', 'wtsd', 'wsd', 'cbet', 'fold_to_cbet', 'check_raise'):
                comparison['recent'][stat] = recent_postflop.get(stat, 0)

        return comparison

    def _get_recent_preflop_stats(self, date_from: str) -> dict:
        """Compute preflop stats for hands from date_from onwards."""
        from collections import defaultdict

        sequences = self.repo.get_preflop_action_sequences(self.year)
        # Filter by date
        recent = [a for a in sequences if (a.get('day') or '') >= date_from]
        if not recent:
            return {}

        hands_actions = defaultdict(list)
        for action in recent:
            hands_actions[action['hand_id']].append(action)

        total = 0
        vpip_c = 0
        pfr_c = 0
        three_bet_opps = 0
        three_bet_c = 0
        fold_3bet_opps = 0
        fold_3bet_c = 0
        ats_opps = 0
        ats_c = 0

        for hand_id, actions in hands_actions.items():
            if not any(a['is_hero'] for a in actions):
                continue
            total += 1

            voluntary = [
                a for a in actions
                if a['action_type'] not in ('post_sb', 'post_bb', 'post_ante')
            ]
            result = CashAnalyzer._analyze_preflop_hand(voluntary)

            if result['vpip']:
                vpip_c += 1
            if result['pfr']:
                pfr_c += 1
            if result['three_bet_opp']:
                three_bet_opps += 1
                if result['three_bet']:
                    three_bet_c += 1
            if result['fold_3bet_opp']:
                fold_3bet_opps += 1
                if result['fold_3bet']:
                    fold_3bet_c += 1
            if result['ats_opp']:
                ats_opps += 1
                if result['ats']:
                    ats_c += 1

        if total == 0:
            return {}

        def pct(n, d):
            return (n / d * 100) if d > 0 else 0.0

        return {
            'total_hands': total,
            'vpip': pct(vpip_c, total),
            'pfr': pct(pfr_c, total),
            'three_bet': pct(three_bet_c, three_bet_opps),
            'fold_to_3bet': pct(fold_3bet_c, fold_3bet_opps),
            'ats': pct(ats_c, ats_opps),
        }

    def _get_recent_postflop_stats(self, date_from: str) -> dict:
        """Compute postflop stats for hands from date_from onwards."""
        from collections import defaultdict

        sequences = self.repo.get_all_action_sequences(self.year)
        recent = [a for a in sequences if (a.get('day') or '') >= date_from]
        if not recent:
            return {}

        hands_actions = defaultdict(list)
        hand_meta = {}
        for action in recent:
            hand_id = action['hand_id']
            hands_actions[hand_id].append(action)
            if hand_id not in hand_meta:
                hand_meta[hand_id] = {
                    'hero_net': action.get('hero_net', 0) or 0,
                }

        saw_flop = 0
        wtsd_c = 0
        wsd_c = 0
        cbet_opps = 0
        cbet_c = 0
        fold_cbet_opps = 0
        fold_cbet_c = 0
        cr_opps = 0
        cr_c = 0
        agg_br = 0
        agg_calls = 0

        for hand_id, actions in hands_actions.items():
            if not any(a['is_hero'] for a in actions):
                continue
            hero_net = hand_meta[hand_id]['hero_net']

            post = CashAnalyzer._analyze_postflop_hand(actions, hero_net)
            if post['saw_flop']:
                saw_flop += 1
            if post['went_to_showdown']:
                wtsd_c += 1
            if post['won_at_showdown']:
                wsd_c += 1
            if post['cbet_opp']:
                cbet_opps += 1
                if post['cbet']:
                    cbet_c += 1
            if post.get('fold_to_cbet_opp'):
                fold_cbet_opps += 1
                if post.get('fold_to_cbet'):
                    fold_cbet_c += 1
            if post.get('check_raise_opp'):
                cr_opps += 1
                if post.get('check_raise'):
                    cr_c += 1
            for street in ('flop', 'turn', 'river'):
                if street in post['hero_aggression']:
                    ha = post['hero_aggression'][street]
                    agg_br += ha['bets'] + ha['raises']
                    agg_calls += ha['calls']

        if saw_flop == 0:
            return {}

        def pct(n, d):
            return (n / d * 100) if d > 0 else 0.0

        return {
            'saw_flop_hands': saw_flop,
            'af': agg_br / agg_calls if agg_calls > 0 else 0.0,
            'wtsd': pct(wtsd_c, saw_flop),
            'wsd': pct(wsd_c, wtsd_c),
            'cbet': pct(cbet_c, cbet_opps),
            'fold_to_cbet': pct(fold_cbet_c, fold_cbet_opps),
            'check_raise': pct(cr_c, cr_opps),
        }
