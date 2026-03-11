"""Expected Value (EV) analysis module.

Calculates equity for all-in hands with showdown, computes EV-adjusted
results, and generates data for EV line vs Real line charts.
"""

import random
from collections import defaultdict
from itertools import combinations

from src.db.repository import Repository


# ── Card & Hand Evaluation ───────────────────────────────────────────

RANK_MAP = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
            '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}


def parse_card(card_str):
    """Parse a card string like 'Ah' into (rank, suit) tuple."""
    card_str = card_str.strip()
    rank = RANK_MAP.get(card_str[0].upper())
    suit = 'hdcs'.index(card_str[1].lower())
    if rank is None:
        raise ValueError(f"Invalid card: {card_str}")
    return (rank, suit)


def parse_cards(cards_str):
    """Parse a space-separated string of cards."""
    if not cards_str or not cards_str.strip():
        return []
    return [parse_card(c) for c in cards_str.strip().split()]


def evaluate_hand(cards):
    """Evaluate the best 5-card hand from 5-7 cards.

    Returns a comparable tuple (higher = better).
    Uses optimized direct evaluation for 7 cards to avoid
    generating all 21 5-card combinations.
    """
    n = len(cards)
    if n < 5:
        return (0,)
    if n == 5:
        return _eval_five(cards)
    # For 6-7 cards, use direct best-hand evaluation
    return _eval_best_seven(cards) if n == 7 else _eval_best_six(cards)


def _eval_best_seven(cards):
    """Evaluate best 5-card hand from exactly 7 cards.

    Instead of C(7,5)=21 combos, evaluate all at once using
    rank/suit analysis of all 7 cards.
    """
    ranks = [c[0] for c in cards]
    suits = [c[1] for c in cards]

    # Count ranks and suits
    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1

    suit_counts = {}
    suit_cards = {}
    for r, s in cards:
        suit_counts[s] = suit_counts.get(s, 0) + 1
        if s not in suit_cards:
            suit_cards[s] = []
        suit_cards[s].append(r)

    # Check for flush (5+ of same suit)
    flush_suit = None
    for s, cnt in suit_counts.items():
        if cnt >= 5:
            flush_suit = s
            break

    # Find all straights in the 7 cards
    unique_ranks = sorted(set(ranks), reverse=True)
    best_straight = _find_best_straight(unique_ranks)

    # Check straight flush
    if flush_suit is not None:
        flush_ranks = sorted(set(suit_cards[flush_suit]), reverse=True)
        sf_high = _find_best_straight(flush_ranks)
        if sf_high:
            return (8, sf_high)

    # Four of a kind
    quads = [r for r, c in rank_counts.items() if c == 4]
    if quads:
        quad_rank = max(quads)
        kicker = max(r for r in ranks if r != quad_rank)
        return (7, quad_rank, kicker)

    # Full house (pick best trip + best pair)
    trips = sorted([r for r, c in rank_counts.items() if c >= 3], reverse=True)
    pairs = sorted([r for r, c in rank_counts.items() if c >= 2], reverse=True)
    if trips:
        best_trip = trips[0]
        # Pair can be second trips or any pair
        best_pair = 0
        for r in pairs:
            if r != best_trip:
                best_pair = r
                break
        if best_pair:
            return (6, best_trip, best_pair)

    # Flush
    if flush_suit is not None:
        flush_top5 = sorted(suit_cards[flush_suit], reverse=True)[:5]
        return (5,) + tuple(flush_top5)

    # Straight
    if best_straight:
        return (4, best_straight)

    # Three of a kind
    if trips:
        best_trip = trips[0]
        kickers = sorted([r for r in ranks if r != best_trip], reverse=True)[:2]
        return (3, best_trip) + tuple(kickers)

    # Two pair
    if len(pairs) >= 2:
        top2 = pairs[:2]
        kicker = max(r for r in ranks if r not in top2)
        return (2, top2[0], top2[1], kicker)

    # One pair
    if pairs:
        pair_rank = pairs[0]
        kickers = sorted([r for r in ranks if r != pair_rank], reverse=True)[:3]
        return (1, pair_rank) + tuple(kickers)

    # High card
    top5 = sorted(ranks, reverse=True)[:5]
    return (0,) + tuple(top5)


def _eval_best_six(cards):
    """Evaluate best 5-card hand from exactly 6 cards."""
    # C(6,5)=6 combos — small enough to enumerate
    best = None
    for combo in combinations(cards, 5):
        val = _eval_five(list(combo))
        if best is None or val > best:
            best = val
    return best


def _find_best_straight(unique_sorted_desc):
    """Find highest straight from sorted unique ranks (descending).

    Returns high card of best straight, or None.
    """
    if len(unique_sorted_desc) < 5:
        return None
    for i in range(len(unique_sorted_desc) - 4):
        if unique_sorted_desc[i] - unique_sorted_desc[i + 4] == 4:
            return unique_sorted_desc[i]
    # Wheel (A-2-3-4-5)
    rank_set = set(unique_sorted_desc)
    if {14, 5, 4, 3, 2} <= rank_set:
        return 5
    return None


def _eval_five(cards):
    """Evaluate exactly 5 cards. Returns ranking tuple.

    Rankings (descending):
    (8, high)                     = Straight Flush
    (7, quad, kicker)             = Four of a Kind
    (6, trip, pair)               = Full House
    (5, r1, r2, r3, r4, r5)      = Flush
    (4, high)                     = Straight
    (3, trip, k1, k2)             = Three of a Kind
    (2, hi_pair, lo_pair, kicker) = Two Pair
    (1, pair, k1, k2, k3)        = One Pair
    (0, r1, r2, r3, r4, r5)      = High Card
    """
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    is_flush = len(set(suits)) == 1

    # Straight detection
    unique = sorted(set(ranks), reverse=True)
    is_straight = False
    straight_high = 0
    if len(unique) >= 5:
        for i in range(len(unique) - 4):
            if unique[i] - unique[i + 4] == 4:
                is_straight = True
                straight_high = unique[i]
                break
        if not is_straight and {14, 5, 4, 3, 2} <= set(unique):
            is_straight = True
            straight_high = 5

    # Rank counts
    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1

    groups = defaultdict(list)
    for r, c in counts.items():
        groups[c].append(r)
    for c in groups:
        groups[c].sort(reverse=True)

    if is_straight and is_flush:
        return (8, straight_high)
    if 4 in groups:
        kickers = [r for r in ranks if r != groups[4][0]]
        return (7, groups[4][0], max(kickers) if kickers else 0)
    if 3 in groups and 2 in groups:
        return (6, groups[3][0], groups[2][0])
    if is_flush:
        return (5,) + tuple(ranks)
    if is_straight:
        return (4, straight_high)
    if 3 in groups:
        kickers = sorted([r for r in ranks if r != groups[3][0]], reverse=True)
        return (3, groups[3][0]) + tuple(kickers[:2])
    if 2 in groups and len(groups[2]) >= 2:
        pairs = groups[2][:2]
        kickers = [r for r in ranks if r not in pairs]
        return (2, pairs[0], pairs[1], max(kickers) if kickers else 0)
    if 2 in groups:
        kickers = sorted([r for r in ranks if r != groups[2][0]], reverse=True)
        return (1, groups[2][0]) + tuple(kickers[:3])
    return (0,) + tuple(ranks)


def calculate_equity(hero_cards, opponents_cards_list, board,
                     simulations=1000, rng=None):
    """Calculate hero's equity against one or more opponents.

    Args:
        hero_cards: list of 2 (rank, suit) tuples
        opponents_cards_list: list of lists, each with 2 (rank, suit) tuples
        board: list of (rank, suit) tuples (0-5 cards)
        simulations: Monte Carlo simulations for preflop/flop
        rng: random.Random instance for reproducibility

    Returns: float 0.0-1.0 (hero's equity)
    """
    if rng is None:
        rng = random.Random()

    cards_needed = 5 - len(board)
    if cards_needed < 0:
        return 0.5

    all_known = set()
    all_known.update(hero_cards)
    for opp in opponents_cards_list:
        all_known.update(opp)
    all_known.update(board)

    deck = [(r, s) for r in range(2, 15) for s in range(4)
            if (r, s) not in all_known]

    if cards_needed == 0:
        return _evaluate_showdown(hero_cards, opponents_cards_list, board)

    # Exact enumeration for 1-2 cards remaining
    if cards_needed <= 2:
        total_score = 0.0
        total = 0
        for combo in combinations(deck, cards_needed):
            full_board = list(board) + list(combo)
            total_score += _evaluate_showdown(
                hero_cards, opponents_cards_list, full_board)
            total += 1
        return total_score / total if total > 0 else 0.5

    # Monte Carlo for 3+ cards
    total_score = 0.0
    for _ in range(simulations):
        remaining = rng.sample(deck, cards_needed)
        full_board = list(board) + remaining
        total_score += _evaluate_showdown(
            hero_cards, opponents_cards_list, full_board)
    return total_score / simulations


def _evaluate_showdown(hero_cards, opponents_cards_list, board):
    """Evaluate a complete showdown. Returns hero's share (0.0, 0.5, or 1.0)."""
    hero_eval = evaluate_hand(list(hero_cards) + list(board))

    best_opp = None
    for opp in opponents_cards_list:
        opp_eval = evaluate_hand(list(opp) + list(board))
        if best_opp is None or opp_eval > best_opp:
            best_opp = opp_eval

    if best_opp is None:
        return 1.0
    if hero_eval > best_opp:
        return 1.0
    if hero_eval == best_opp:
        return 0.5
    return 0.0


# ── EV Analyzer ──────────────────────────────────────────────────────

class EVAnalyzer:
    """Analyze Expected Value for all-in hands with showdown."""

    def __init__(self, repo: Repository, year: str = '2026'):
        self.repo = repo
        self.year = year

    def get_ev_analysis(self) -> dict:
        """Calculate EV analysis for all cash hands.

        Returns dict with:
        - overall: summary stats
        - by_stakes: per-stakes breakdown
        - chart_data: list of dicts for SVG chart
        """
        all_hands = self.repo.get_cash_hands(self.year)
        allin_hands = self.repo.get_allin_hands(self.year)

        if not all_hands:
            return self._empty_result()

        # Calculate equity for each all-in hand
        allin_ev = {}
        for h in allin_hands:
            ev_data = self._compute_hand_ev(h)
            if ev_data is not None:
                allin_ev[h['hand_id']] = ev_data

        # Build cumulative data
        cumulative_real = 0.0
        cumulative_ev = 0.0
        chart_data = []

        stakes_data = defaultdict(lambda: {
            'total_hands': 0, 'allin_hands': 0,
            'real_net': 0.0, 'ev_net': 0.0, 'bb_size': 0.0,
        })

        for i, h in enumerate(all_hands):
            net = h.get('net', 0) or 0
            bb = h.get('blinds_bb') or 0.5
            sb = h.get('blinds_sb') or (bb / 2)
            stakes_key = f"${sb:.2f}/${bb:.2f}"

            cumulative_real += net

            if h['hand_id'] in allin_ev:
                ev_net_hand = allin_ev[h['hand_id']]['ev_net']
                cumulative_ev += ev_net_hand
                stakes_data[stakes_key]['allin_hands'] += 1
            else:
                ev_net_hand = net
                cumulative_ev += net

            stakes_data[stakes_key]['total_hands'] += 1
            stakes_data[stakes_key]['real_net'] += net
            stakes_data[stakes_key]['ev_net'] += ev_net_hand
            stakes_data[stakes_key]['bb_size'] = bb

            chart_data.append({
                'hand': i + 1,
                'real': round(cumulative_real, 2),
                'ev': round(cumulative_ev, 2),
            })

        total_hands = len(all_hands)
        total_allin = len(allin_ev)
        luck_factor = cumulative_real - cumulative_ev

        # Overall bb/100
        avg_bb = self._weighted_avg_bb(all_hands)
        bb100_real = ((cumulative_real / avg_bb / total_hands * 100)
                      if avg_bb > 0 and total_hands > 0 else 0)
        bb100_ev = ((cumulative_ev / avg_bb / total_hands * 100)
                    if avg_bb > 0 and total_hands > 0 else 0)

        # Format by_stakes
        by_stakes = {}
        for sk, data in sorted(stakes_data.items()):
            th = data['total_hands']
            bb = data['bb_size']
            by_stakes[sk] = {
                'total_hands': th,
                'allin_hands': data['allin_hands'],
                'real_net': round(data['real_net'], 2),
                'ev_net': round(data['ev_net'], 2),
                'luck_factor': round(data['real_net'] - data['ev_net'], 2),
                'bb100_real': (round(data['real_net'] / bb / th * 100, 2)
                               if th > 0 and bb > 0 else 0),
                'bb100_ev': (round(data['ev_net'] / bb / th * 100, 2)
                             if th > 0 and bb > 0 else 0),
            }

        # Downsample chart data for SVG (max 500 points)
        chart_sampled = self._downsample(chart_data, 500)

        return {
            'overall': {
                'total_hands': total_hands,
                'allin_hands': total_allin,
                'real_net': round(cumulative_real, 2),
                'ev_net': round(cumulative_ev, 2),
                'luck_factor': round(luck_factor, 2),
                'bb100_real': round(bb100_real, 2),
                'bb100_ev': round(bb100_ev, 2),
            },
            'by_stakes': by_stakes,
            'chart_data': chart_sampled,
        }

    def _compute_hand_ev(self, hand: dict):
        """Compute EV for a single all-in hand with showdown.

        Returns dict with 'equity', 'ev_net', 'ev_diff' or None if can't calculate.
        """
        hero_str = hand.get('hero_cards')
        opp_str = hand.get('opponent_cards')
        if not hero_str or not opp_str:
            return None

        try:
            hero_cards = parse_cards(hero_str)
            if len(hero_cards) != 2:
                return None

            # Parse opponent cards (pipe-separated for multi-way)
            opp_groups = opp_str.split('|')
            opponents = []
            for group in opp_groups:
                cards = parse_cards(group.strip())
                if len(cards) == 2:
                    opponents.append(cards)

            if not opponents:
                return None

            # Determine board at time of all-in
            board = self._get_board_at_allin(hand)

            equity = calculate_equity(hero_cards, opponents, board)

            pot = hand.get('pot_total', 0) or 0
            invested = hand.get('invested', 0) or 0
            actual_net = hand.get('net', 0) or 0

            ev_net = equity * pot - invested
            ev_diff = actual_net - ev_net

            return {
                'equity': round(equity, 4),
                'ev_net': round(ev_net, 2),
                'ev_diff': round(ev_diff, 2),
            }
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _get_board_at_allin(hand: dict) -> list[tuple[int, int]]:
        """Get board cards visible at the time of all-in."""
        allin_street = hand.get('allin_street', 'preflop')

        board = []
        flop_str = hand.get('board_flop')
        turn_str = hand.get('board_turn')
        river_str = hand.get('board_river')

        if allin_street == 'preflop':
            return []

        if flop_str:
            board.extend(parse_cards(flop_str))

        if allin_street in ('turn', 'river') and turn_str:
            board.extend(parse_cards(turn_str))

        if allin_street == 'river' and river_str:
            board.extend(parse_cards(river_str))

        return board

    @staticmethod
    def _weighted_avg_bb(hands: list[dict]) -> float:
        """Calculate weighted average big blind size across hands."""
        if not hands:
            return 0.5
        total_bb = sum(h.get('blinds_bb', 0.5) or 0.5 for h in hands)
        return total_bb / len(hands)

    @staticmethod
    def _downsample(data: list, max_points: int) -> list:
        """Downsample data to max_points, keeping first and last."""
        if len(data) <= max_points:
            return data
        step = len(data) / max_points
        result = []
        for i in range(max_points - 1):
            idx = int(i * step)
            result.append(data[idx])
        result.append(data[-1])
        return result

    def get_session_ev_analysis(self, session: dict) -> dict:
        """Calculate EV analysis for a single cash session.

        Args:
            session: dict with 'start_time' and 'end_time' keys.

        Returns dict with:
        - allin_hands, total_hands, real_net, ev_net, luck_factor
        - bb100_real, bb100_ev
        - chart_data: list of dicts for mini SVG chart
        """
        all_hands = self.repo.get_hands_for_session(session)
        if not all_hands:
            return self._empty_session_ev()

        # Get all-in hands for the year and filter to session range
        allin_hands = self.repo.get_allin_hands(self.year)
        start = session.get('start_time', '')
        end = session.get('end_time', '')
        session_allin = [
            h for h in allin_hands
            if start <= (h.get('date') or '') <= end
        ]

        # Calculate equity for each all-in hand
        allin_ev = {}
        for h in session_allin:
            ev_data = self._compute_hand_ev(h)
            if ev_data is not None:
                allin_ev[h['hand_id']] = ev_data

        # Build cumulative data
        cumulative_real = 0.0
        cumulative_ev = 0.0
        chart_data = []

        for i, h in enumerate(all_hands):
            net = h.get('net', 0) or 0
            cumulative_real += net

            if h['hand_id'] in allin_ev:
                ev_net_hand = allin_ev[h['hand_id']]['ev_net']
                cumulative_ev += ev_net_hand
            else:
                ev_net_hand = net
                cumulative_ev += net

            chart_data.append({
                'hand': i + 1,
                'real': round(cumulative_real, 2),
                'ev': round(cumulative_ev, 2),
            })

        total_hands = len(all_hands)
        total_allin = len(allin_ev)
        luck_factor = cumulative_real - cumulative_ev

        # bb/100
        avg_bb = self._weighted_avg_bb(all_hands)
        bb100_real = ((cumulative_real / avg_bb / total_hands * 100)
                      if avg_bb > 0 and total_hands > 0 else 0)
        bb100_ev = ((cumulative_ev / avg_bb / total_hands * 100)
                    if avg_bb > 0 and total_hands > 0 else 0)

        # Downsample chart for mini SVG (max 100 points)
        chart_sampled = self._downsample(chart_data, 100)

        return {
            'total_hands': total_hands,
            'allin_hands': total_allin,
            'real_net': round(cumulative_real, 2),
            'ev_net': round(cumulative_ev, 2),
            'luck_factor': round(luck_factor, 2),
            'bb100_real': round(bb100_real, 2),
            'bb100_ev': round(bb100_ev, 2),
            'chart_data': chart_sampled,
        }

    @staticmethod
    def _empty_session_ev() -> dict:
        return {
            'total_hands': 0, 'allin_hands': 0,
            'real_net': 0, 'ev_net': 0, 'luck_factor': 0,
            'bb100_real': 0, 'bb100_ev': 0,
            'chart_data': [],
        }

    @staticmethod
    def _empty_result() -> dict:
        return {
            'overall': {
                'total_hands': 0, 'allin_hands': 0,
                'real_net': 0, 'ev_net': 0, 'luck_factor': 0,
                'bb100_real': 0, 'bb100_ev': 0,
            },
            'by_stakes': {},
            'chart_data': [],
        }

    # ── Decision-Tree EV Analysis ─────────────────────────────────────

    @staticmethod
    def _compute_decision_ev(actions: list[dict], hands: list[dict]) -> dict:
        """Compute decision-tree EV from action sequences and hands.

        Shared logic for both cash and tournament decision EV analysis.
        Groups hero decisions by type and street, computes average net outcomes
        per decision context, and identifies EV leaks.

        Args:
            actions: list of action dicts (from repo query)
            hands: list of hand dicts (from repo query)

        Returns dict with:
        - total_hands: count of hands analyzed
        - by_street: per-street metrics for fold/call/raise decisions
        - leaks: top 5 EV leaks with descriptions and suggestions
        - chart_data: list of dicts for decision EV bar chart
        """
        if not hands:
            return EVAnalyzer._empty_decision_ev_result()

        hand_lookup = {h['hand_id']: h for h in hands}

        hand_actions_map = defaultdict(list)
        for a in actions:
            hand_actions_map[a['hand_id']].append(a)

        streets = ('preflop', 'flop', 'turn', 'river')
        _skip = {'post_sb', 'post_bb', 'post_ante', 'check'}

        # Per (street, decision) net accumulators
        stats = {
            st: {dec: {'count': 0, 'total_net': 0.0}
                 for dec in ('fold', 'call', 'raise')}
            for st in streets
        }
        # Context-specific accumulators for leak detection
        contexts: dict = defaultdict(lambda: {'count': 0, 'wins': 0, 'total_net': 0.0})

        for hand_id, hand_acts in hand_actions_map.items():
            hand = hand_lookup.get(hand_id)
            if not hand:
                continue
            hand_net = hand.get('net', 0) or 0

            street_acts: dict = defaultdict(list)
            for a in hand_acts:
                street_acts[a['street']].append(a)

            for street in streets:
                acts = sorted(street_acts.get(street, []),
                              key=lambda x: x['sequence_order'])
                if not acts:
                    continue

                hero_acts = [
                    a for a in acts
                    if a['is_hero'] and a['action_type'] not in _skip
                ]
                if not hero_acts:
                    continue

                first_hero = hero_acts[0]
                atype = first_hero['action_type']

                if atype == 'fold':
                    decision = 'fold'
                elif atype == 'call':
                    decision = 'call'
                elif atype in ('raise', 'bet', 'all-in'):
                    decision = 'raise'
                else:
                    continue

                stats[street][decision]['count'] += 1
                stats[street][decision]['total_net'] += hand_net

                # Determine context: facing opponent bet or hero initiative
                seq = first_hero['sequence_order']
                facing_bet = any(
                    a for a in acts
                    if not a['is_hero']
                    and a['sequence_order'] < seq
                    and a['action_type'] in ('bet', 'raise', 'all-in')
                )
                context = 'vs_bet' if facing_bet else 'initiative'
                ctx_key = f"{street}_{decision}_{context}"
                contexts[ctx_key]['count'] += 1
                contexts[ctx_key]['total_net'] += hand_net
                if hand_net > 0:
                    contexts[ctx_key]['wins'] += 1

        by_street = {}
        for street in streets:
            by_street[street] = {}
            for dec in ('fold', 'call', 'raise'):
                cnt = stats[street][dec]['count']
                net = stats[street][dec]['total_net']
                by_street[street][dec] = {
                    'count': cnt,
                    'total_net': round(net, 2),
                    'avg_net': round(net / cnt, 2) if cnt > 0 else 0.0,
                }

        leaks = EVAnalyzer._identify_ev_leaks(dict(contexts))

        chart_data = [
            {
                'street': street,
                'fold_avg': by_street[street]['fold']['avg_net'],
                'call_avg': by_street[street]['call']['avg_net'],
                'raise_avg': by_street[street]['raise']['avg_net'],
            }
            for street in streets
        ]

        return {
            'total_hands': len(hands),
            'by_street': by_street,
            'leaks': leaks,
            'chart_data': chart_data,
        }

    def get_decision_ev_analysis(self) -> dict:
        """Calculate decision-tree EV for fold, call, and raise decisions on cash hands.

        Returns dict with total_hands, by_street, leaks, chart_data.
        """
        actions = self.repo.get_all_action_sequences(self.year)
        hands = self.repo.get_cash_hands(self.year)
        return self._compute_decision_ev(actions, hands)

    def get_tournament_decision_ev_analysis(self) -> dict:
        """Calculate decision-tree EV for fold/call/raise on tournament hands.

        Uses tournament action sequences and hands. Net values are in chips.

        Returns dict with total_hands, by_street, leaks, chart_data.
        """
        actions = self.repo.get_tournament_all_actions(self.year)
        hands = self.repo.get_tournament_hands(self.year)
        return self._compute_decision_ev(actions, hands)

    @staticmethod
    def _identify_ev_leaks(contexts: dict) -> list:
        """Find top 5 EV leaks from decision context data.

        Args:
            contexts: dict mapping context keys to {count, wins, total_net}.

        Returns list of up to 5 leak dicts sorted by total loss (worst first).
        """
        leaks = []
        for ctx_key, data in contexts.items():
            count = data['count']
            if count < 5:
                continue
            total_net = data['total_net']
            if total_net >= 0:
                continue

            # Parse ctx_key: "{street}_{decision}_{context}"
            # Note: context can be 'vs_bet' (contains underscore)
            # Streets and decisions never contain underscores, so split
            # as: first part = street, second = decision, rest = context
            parts = ctx_key.split('_')
            if len(parts) < 3:
                continue

            street = parts[0]
            decision = parts[1]
            context = '_'.join(parts[2:])

            win_rate = data['wins'] / count * 100
            desc, suggestion = EVAnalyzer._leak_description(
                street, decision, context, count, win_rate, total_net)

            leaks.append({
                'description': desc,
                'count': count,
                'total_loss': round(total_net, 2),
                'avg_loss': round(total_net / count, 2),
                'suggestion': suggestion,
            })

        leaks.sort(key=lambda x: x['total_loss'])
        return leaks[:5]

    @staticmethod
    def _leak_description(street: str, decision: str, context: str,
                          count: int, win_rate: float, total_net: float):
        """Generate human-readable description and suggestion for an EV leak."""
        street_pt = {
            'preflop': 'Preflop', 'flop': 'Flop',
            'turn': 'Turn', 'river': 'River',
        }.get(street, street.capitalize())

        if decision == 'fold' and context == 'vs_bet':
            desc = f"Fold excessivo vs bet no {street_pt} ({count} vezes)"
            suggestion = (
                f"Defenda mais vs bets no {street_pt}: "
                f"use pot odds para calcular equity m\u00ednima necess\u00e1ria"
            )
        elif decision == 'call' and context == 'vs_bet':
            desc = (f"Calls no {street_pt} com baixa win rate "
                    f"({win_rate:.0f}%)")
            suggestion = (
                f"Selecione calls mais tight no {street_pt}: "
                f"compare equity vs pot odds antes de chamar"
            )
        elif decision == 'raise' and context == 'vs_bet':
            desc = (f"Raise vs bet no {street_pt} com EV negativo "
                    f"({count} spots)")
            suggestion = (
                f"Escolha melhores spots para raise no {street_pt}: "
                f"polarize range entre value e bluffs"
            )
        elif decision == 'fold' and context == 'initiative':
            desc = f"Check-fold no {street_pt} ({count} vezes)"
            suggestion = (
                f"Adicione bluffs ao range de check no {street_pt} "
                f"ou c-bet mais seletivo para proteger sua range"
            )
        elif decision == 'call' and context == 'initiative':
            desc = f"Limp/call no {street_pt} ({count} spots passivos)"
            suggestion = (
                f"Prefira raise ou fold no {street_pt}: "
                f"callar sem iniciativa reduz sua range advantage"
            )
        elif decision == 'raise' and context == 'initiative':
            desc = f"Bet/raise no {street_pt} sem retorno positivo"
            suggestion = (
                f"Revise sizing e frequ\u00eancia de bet no {street_pt}: "
                f"target value bets com m\u00e3os fortes, bluffs com equity"
            )
        else:
            desc = f"{street_pt} {decision} decision com EV negativo"
            suggestion = f"Revise suas decis\u00f5es de {decision} no {street_pt}"

        return desc, suggestion

    @staticmethod
    def _empty_decision_ev_result() -> dict:
        """Return empty decision EV result structure."""
        def _empty_street():
            return {
                dec: {'count': 0, 'total_net': 0.0, 'avg_net': 0.0}
                for dec in ('fold', 'call', 'raise')
            }
        return {
            'total_hands': 0,
            'by_street': {
                st: _empty_street()
                for st in ('preflop', 'flop', 'turn', 'river')
            },
            'leaks': [],
            'chart_data': [],
        }
