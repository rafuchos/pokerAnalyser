"""Lesson Classifier Engine: classifies poker hands into RegLife lessons.

Each hand can match multiple lessons across different streets.
Detection rules are based on action patterns, positions, and game context.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.db.repository import Repository


@dataclass
class LessonMatch:
    """A single hand-to-lesson classification result."""
    hand_id: str
    lesson_id: int
    street: Optional[str] = None  # preflop, flop, turn, river, or None
    executed_correctly: Optional[int] = None  # 1=correct, 0=incorrect, None=unknown
    confidence: float = 1.0
    notes: str = ''


class LessonClassifier:
    """Classifies poker hands into RegLife study lessons.

    Uses action patterns, position, stack depth, and game context
    to detect which lesson(s) apply to each hand.
    """

    # Position groups
    STEAL_POSITIONS = {'CO', 'BTN', 'SB'}
    EARLY_POSITIONS = {'UTG', 'UTG+1', 'EP', 'LJ'}
    MIDDLE_POSITIONS = {'MP', 'HJ'}

    # ── RFI Range Data (from RegLife 'Ranges de RFI em cEV' PDF) ─────
    _RANK_ORDER = '23456789TJQKA'

    # RFI hand tiers: tier N = can open from position tier N or wider.
    # Tier 1: EP (UTG/UTG+1) ~17% range
    _RFI_TIER1 = {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s',
        'KQs', 'KJs', 'KTs', 'K9s', 'K8s', 'K7s',
        'QJs', 'QTs', 'Q9s',
        'JTs', 'J9s',
        'T9s', 'T8s',
        '98s', '87s', '76s', '65s', '54s',
        'AKo', 'AQo', 'AJo', 'ATo',
    }
    # Tier 2: MP (LJ/HJ) adds ~10% → total ~28%
    _RFI_TIER2 = {
        '66', '55',
        'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        'K6s', 'K5s',
        'Q8s', 'J8s', 'T7s', '97s', '86s', '75s', '64s', '53s',
        'A9o', 'KQo', 'KJo', 'KTo', 'QJo', 'QTo', 'JTo',
    }
    # Tier 3: CO adds ~9% → total ~37%
    _RFI_TIER3 = {
        '44', '33', '22',
        'K4s', 'K3s', 'K2s',
        'Q7s', 'Q6s', 'Q5s', 'Q4s', 'Q3s', 'Q2s',
        'J7s', 'T6s', '96s', '85s', '74s', '63s', '52s', '43s',
        'A8o', 'A7o', 'A6o', 'A5o',
        'K9o', 'Q9o', 'J9o', 'T9o',
    }
    # Tier 4: BTN adds ~17% → total ~54%
    _RFI_TIER4 = {
        'J6s', 'J5s', 'J4s', 'J3s', 'J2s',
        'T5s', 'T4s', 'T3s', 'T2s',
        '95s', '94s', '93s', '92s',
        '84s', '83s', '82s',
        '73s', '72s', '62s', '42s', '32s',
        'A4o', 'A3o', 'A2o',
        'K8o', 'K7o', 'K6o', 'K5o', 'K4o', 'K3o', 'K2o',
        'Q8o', 'Q7o', 'Q6o',
        'J8o', 'J7o',
        'T8o', 'T7o',
        '98o', '97o', '87o', '86o',
        '76o', '75o', '65o', '64o', '54o', '53o',
    }

    # Position → maximum hand tier allowed for RFI
    _RFI_POS_MAX_TIER = {
        'UTG': 1, 'EP': 1, 'UTG+1': 1, 'UTG+2': 1,
        'LJ': 2, 'MP': 2, 'HJ': 2,
        'CO': 3,
        'BTN': 4, 'SB': 4,
    }

    # ── Multiway BB Defense Data (from RegLife 'Defesa Multiway do BB' PDF) ──
    # Hands that should always defend in BB vs multiway action.
    # Folding these is a clear mistake; calling/raising is correct.
    _MWBB_DEFEND = {
        # All pairs: set mining is very profitable with multiple callers
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', '44', '33', '22',
        # Suited aces: nut flush draws have enormous value multiway
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        # Suited kings and strong suited broadways
        'KQs', 'KJs', 'KTs', 'K9s', 'K8s', 'K7s',
        'QJs', 'QTs', 'Q9s', 'Q8s',
        'JTs', 'J9s', 'J8s',
        # Suited connectors and 1-gappers (great implied odds multiway)
        'T9s', 'T8s', 'T7s',
        '98s', '97s', '96s',
        '87s', '86s', '85s',
        '76s', '75s', '74s',
        '65s', '64s', '63s',
        '54s', '53s', '52s',
        '43s', '42s', '32s',
        # Strong offsuit broadways
        'AKo', 'AQo', 'AJo', 'ATo',
        'KQo', 'KJo',
    }
    # Marginal hands: defending or folding is context-dependent
    # (number of callers, stack depth, and opponent tendencies matter)
    _MWBB_MARGINAL = {
        # Weak suited hands (flush potential but poor connectivity)
        'K6s', 'K5s', 'K4s', 'K3s', 'K2s',
        'Q7s', 'Q6s', 'Q5s', 'Q4s', 'Q3s', 'Q2s',
        'J7s', 'J6s', 'J5s', 'J4s', 'J3s', 'J2s',
        'T6s', 'T5s', 'T4s', 'T3s', 'T2s',
        '95s', '94s', '93s', '92s',
        '84s', '83s', '82s',
        '73s', '72s', '62s',
        # Medium offsuit hands (some equity but dominated often)
        'QJo', 'QTo', 'JTo',
        'A9o', 'A8o', 'A7o', 'A6o', 'A5o', 'A4o', 'A3o', 'A2o',
        'K9o', 'K8o', 'K7o',
        'Q9o', 'J9o', 'T9o',
        '98o', '87o', '76o', '65o', '54o',
    }
    # All other hands (offsuit with no pair, no suit, poor connectivity) → fold

    # ── BB Pre-Flop Defense Data (from RegLife 'Jogando no Big Blind - Pre-Flop') ──
    # Hands the BB should defend (call or 3-bet) vs a single raise.
    # Tiered by hand strength: tier 1 = defend vs any opener; tier 4 = defend vs BTN/SB only.

    # Tier 1: Always defend vs any opener, including UTG
    _BB_TIER1 = {
        # Pairs 77+ (strong equity and pair value)
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77',
        # All suited aces (nut flush draws are always valuable)
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        # Top suited broadways and kings
        'KQs', 'KJs', 'KTs', 'K9s',
        'QJs', 'QTs', 'Q9s',
        'JTs', 'J9s',
        # Strong suited connectors
        'T9s', '98s', '87s', '76s', '65s', '54s',
        # Strong offsuit broadways
        'AKo', 'AQo', 'AJo',
        'KQo',
    }
    # Tier 2: Defend vs MP/HJ or later (~28-30% from BB)
    _BB_TIER2 = {
        # Small pairs (set mining, pair equity)
        '66', '55', '44', '33', '22',
        # Medium suited kings and queens
        'K8s', 'K7s', 'K6s',
        'Q8s', 'J8s', 'T8s',
        # Suited 1-gappers and weaker connectors
        '97s', '86s', '75s', '64s', '53s', '43s', '42s', '32s',
        # Medium offsuit broadways
        'ATo',
        'KJo', 'KTo',
    }
    # Tier 3: Defend vs CO or later (~38-42% from BB)
    _BB_TIER3 = {
        # Weak suited kings
        'K5s', 'K4s', 'K3s', 'K2s',
        # Medium suited queens and weaker
        'Q7s', 'Q6s',
        'J7s', 'T7s', '96s', '85s', '74s', '63s', '52s',
        # Medium offsuit
        'A9o', 'A8o',
        'QJo', 'QTo', 'JTo',
    }
    # Tier 4: Defend vs BTN/SB only (widest defense range, ~50%)
    _BB_TIER4 = {
        # Weak suited queens, jacks, tens
        'Q5s', 'Q4s', 'Q3s', 'Q2s',
        'J6s', 'J5s', 'J4s', 'J3s', 'J2s',
        'T6s', 'T5s', 'T4s', 'T3s', 'T2s',
        # Very weak suited hands
        '95s', '94s', '93s', '92s', '84s', '83s', '82s', '73s', '72s', '62s',
        # Medium offsuit aces and kings
        'A7o', 'A6o', 'A5o', 'A4o', 'A3o', 'A2o',
        'K9o', 'K8o', 'K7o',
        # Connected medium offsuit
        'Q9o', 'Q8o',
        'J9o',
        'T9o', '98o', '87o', '76o', '65o', '54o',
    }
    # Position of single opener → max tier the BB should defend
    _BB_POS_DEFEND_TIER = {
        'UTG': 1, 'EP': 1, 'UTG+1': 1, 'UTG+2': 1,
        'LJ': 2, 'MP': 2, 'HJ': 2,
        'CO': 3,
        'BTN': 4, 'SB': 4,
    }

    # ── Flat / 3-Bet Range Data (from RegLife 'Ranges de Flat e 3-BET' PDF) ─────
    # When facing an open raise, which hands should flat, 3-bet, or fold.
    # Simplified into tiers by caller position vs opener position.

    # Flat range: hands good enough to call an open raise (position-dependent).
    # Tier 1: call vs EP opener from any position (tightest flat range).
    _FLAT_TIER1 = {
        # Premium pairs trap/call for deception + suited connectors for implied odds
        'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55',
        'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        'KQs', 'KJs', 'KTs', 'K9s',
        'QJs', 'QTs', 'Q9s',
        'JTs', 'J9s',
        'T9s', 'T8s',
        '98s', '97s',
        '87s', '86s',
        '76s', '75s',
        '65s', '64s',
        '54s', '53s',
    }
    # Tier 2: call vs MP/HJ opener (slightly wider, includes suited broadways)
    _FLAT_TIER2 = {
        '44', '33', '22',
        'K8s', 'K7s',
        'Q8s', 'J8s', 'T7s',
        '96s', '85s', '74s', '63s',
        'AKo',  # AKo can flat vs MP with deep stacks
    }
    # Tier 3: call vs CO/BTN opener (wide flat range with connectors + gappers)
    _FLAT_TIER3 = {
        'K6s', 'K5s', 'K4s', 'K3s', 'K2s',
        'Q7s', 'Q6s', 'Q5s', 'Q4s',
        'J7s', 'J6s', 'T6s', 'T5s',
        '95s', '94s', '84s', '83s',
        '73s', '72s', '62s', '52s', '43s', '42s', '32s',
        'AQo', 'AJo', 'ATo', 'A9o',
        'KQo', 'KJo', 'KTo', 'K9o',
        'QJo', 'QTo', 'Q9o',
        'JTo', 'J9o',
        'T9o', 'T8o',
        '98o', '87o',
    }

    # 3-Bet range: hands that should 3-bet an open raise.
    # Tier 1: always 3-bet vs any opener
    _3BET_TIER1 = {
        'AA',
        'AKs', 'AKo',
    }
    # Tier 2: 3-bet vs MP+ opener
    _3BET_TIER2 = {
        'KK', 'QQ',
        'AQs', 'AQo',
    }
    # Tier 3: 3-bet vs CO+ opener (polarized: value + bluffs)
    _3BET_TIER3 = {
        'JJ', 'TT',
        'AJs', 'ATs',
        'A5s', 'A4s', 'A3s',  # suited ace blockers as bluffs
        'KQs',
        'KJo', 'KTo', 'QJo',  # off-suited broadways as bluffs (fold equity)
    }
    # Tier 4: 3-bet vs BTN opener (wide 3-bet from blinds/late pos)
    _3BET_TIER4 = {
        '99', '88',
        'A9s', 'A8s', 'A7s', 'A6s', 'A2s',
        'KJs', 'KTs',
        'QJs', 'QTs',
        'JTs',
        'AJo', 'ATo',
        'KQo',
    }

    # Caller position → max flat tier + 3-bet tier
    _FLAT_POS_MAX_TIER = {
        'UTG': 1, 'EP': 1, 'UTG+1': 1, 'UTG+2': 1,
        'LJ': 1, 'MP': 1, 'HJ': 2,
        'CO': 3,
        'BTN': 3, 'SB': 3,
    }
    _3BET_POS_MAX_TIER = {
        'UTG': 1, 'EP': 1, 'UTG+1': 1, 'UTG+2': 1,
        'LJ': 1, 'MP': 2, 'HJ': 2,
        'CO': 3,
        'BTN': 4, 'SB': 4, 'BB': 4,
    }

    # ── Reaction vs 3-Bet Range Data (from RegLife 'Ranges de reação vs 3-bet') ──
    # How to react when facing a 3-bet after opening.
    # Always continue: these hands should never fold to a 3-bet.
    _VS3BET_CONTINUE = {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55',
        'AKs', 'AQs', 'AJs', 'ATs',
        'KQs', 'KJs', 'KTs',
        'QJs', 'QTs',
        'JTs',
        'T9s', '98s', '87s', '76s', '65s', '54s',
        'AKo', 'AQo',
    }
    # 4-bet range: hands that should 4-bet (for value or as bluffs).
    _VS3BET_4BET = {
        'AA', 'KK', 'QQ',
        'AKs', 'AKo',
    }
    # Marginal: continue when in position, lean fold when OOP vs tight 3-bet.
    _VS3BET_MARGINAL = {
        '44', '33', '22',
        'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        'K9s', 'K8s', 'K7s',
        'Q9s', 'Q8s',
        'J9s', 'J8s',
        'T8s', '97s', '86s', '75s', '64s', '53s',
        'AJo', 'ATo',
        'KQo', 'KJo',
        'QJo', 'JTo',
    }

    # ── Squeeze Range Data (from RegLife 'SQUEEZE' PDF) ─────────────
    # Squeeze ranges when facing open + call.
    # Linear squeeze range for early/middle positions (tight).
    _SQUEEZE_TIER1 = {
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
        'AKs', 'AQs', 'AJs', 'ATs', 'A5s',
        'KQs', 'KJs', 'KTs',
        'QJs', 'JTs',
        'AKo', 'AQo',
    }
    # Wider squeeze range for BTN/late position (in position squeeze).
    _SQUEEZE_TIER2 = {
        '77', '66', '55', '44', '33', '22',
        'A9s', 'A8s', 'A7s', 'A6s', 'A4s', 'A3s', 'A2s',
        'K9s', 'K8s',
        'QTs', 'Q9s',
        'J9s', 'J8s',
        'T9s', 'T8s',
        '98s', '97s',
        '87s', '86s',
        '76s', '75s',
        '65s', '64s',
        '54s', '53s',
        'AJo', 'ATo', 'A9o',
        'KQo', 'KJo', 'KTo',
        'QJo',
    }
    # Position → max squeeze tier allowed.
    _SQUEEZE_POS_MAX_TIER = {
        'UTG': 1, 'EP': 1, 'UTG+1': 1, 'UTG+2': 1,
        'LJ': 1, 'MP': 1, 'HJ': 1,
        'CO': 2,
        'BTN': 2, 'SB': 2, 'BB': 2,
    }

    # ── Open Shove cEV 10BB Range Data (from RegLife 'Ranges de Open Shove cEV 10BB' PDF) ──
    # Open shove ranges for ≤10BB stacks (all-in as first raise, preflop).
    # At 10BB, GTO solution strongly favors shoving a wide range vs folding/minraising.

    # Tier 1: profitable shove from any position including UTG (~35% range).
    _OPEN_SHOVE_TIER1 = {
        # All pairs: always profitable vs typical calling range at 10BB
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', '44', '33', '22',
        # All suited aces: blockers + flush equity + domination potential
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        # Suited broadways
        'KQs', 'KJs', 'KTs',
        # Strong offsuit hands
        'AKo', 'AQo', 'AJo', 'ATo',
    }
    # Tier 2: shove from MP/HJ or later (~50-55% total range).
    _OPEN_SHOVE_TIER2 = {
        # Medium suited kings
        'K9s', 'K8s', 'K7s', 'K6s', 'K5s',
        # More suited broadways
        'QJs', 'QTs', 'Q9s',
        'JTs', 'J9s',
        'T9s', 'T8s',
        '98s', '87s',
        # Medium offsuit
        'A9o', 'A8o', 'A7o',
        'KQo', 'KJo',
    }
    # Tier 3: shove from CO or later (~62-65% total range).
    _OPEN_SHOVE_TIER3 = {
        # Weak suited kings
        'K4s', 'K3s', 'K2s',
        # More suited connectors and gappers
        '76s', '65s', '54s',
        'Q8s', 'J8s',
        '97s', '86s', '75s',
        # Weaker offsuit
        'A6o', 'A5o', 'A4o', 'A3o', 'A2o',
        'KTo', 'K9o',
        'QJo', 'QTo',
        'JTo',
    }
    # Tier 4: shove from BTN/SB only (~72-75% total, very wide).
    _OPEN_SHOVE_TIER4 = {
        # Weak suited queens, jacks, tens
        'Q7s', 'Q6s', 'Q5s', 'Q4s',
        'J7s', 'J6s',
        'T7s', 'T6s',
        '96s', '85s', '74s', '64s', '53s', '43s',
        # Offsuit medium hands
        'K8o', 'K7o', 'K6o',
        'Q9o', 'Q8o',
        'J9o', 'J8o',
        'T9o', 'T8o',
        '98o', '87o', '76o',
    }

    # Position → maximum hand tier allowed for open shove at 10BB
    _OPEN_SHOVE_POS_MAX_TIER = {
        'UTG': 1, 'EP': 1, 'UTG+1': 1, 'UTG+2': 1,
        'LJ': 1, 'MP': 2, 'HJ': 2,
        'CO': 3,
        'BTN': 4, 'SB': 4,
    }

    # ── SB vs BB Blind War Data (from RegLife 'O Conceito de Blind War - SB vs BB') ──
    # Additional hands SB can profitably steal with vs sole BB opponent.
    # SB opens ~60% in blind war: all RFI Tier 1-4 (BTN range, ~54%) + these extras.
    _SB_WAR_EXTRA = {
        # Weak Q-high offsuit (below Q6o which is already in BTN Tier 4)
        'Q5o', 'Q4o', 'Q3o', 'Q2o',
        # Weak J-high offsuit (below J7o)
        'J6o', 'J5o', 'J4o', 'J3o', 'J2o',
        # Weak T-high offsuit (below T7o)
        'T6o', 'T5o', 'T4o', 'T3o', 'T2o',
        # 9-x offsuit (96o and below not in BTN range)
        '96o', '95o', '94o', '93o', '92o',
        # 8-x offsuit (below 86o)
        '85o', '84o', '83o', '82o',
        # 7-x offsuit (below 75o)
        '74o', '73o', '72o',
        # Low connected offsuit
        '63o', '53o',
    }

    # ── BB vs SB Blind War Data (from RegLife 'Blind War BB vs SB') ──
    # BB defense ranges in a blind war vs SB steal.
    # BB defends ~65% due to positional advantage (BB is IP vs SB postflop)
    # and SB's wide range (making BB's relative hand strength better).
    _BW_BB_DEFEND = {
        # All pairs: always defend in blind war
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', '44', '33', '22',
        # All suited aces (flush equity + pair outs always valuable)
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        # All other suited hands (flush draws are powerful in HU pots)
        'KQs', 'KJs', 'KTs', 'K9s', 'K8s', 'K7s', 'K6s', 'K5s', 'K4s', 'K3s', 'K2s',
        'QJs', 'QTs', 'Q9s', 'Q8s', 'Q7s', 'Q6s', 'Q5s', 'Q4s', 'Q3s', 'Q2s',
        'JTs', 'J9s', 'J8s', 'J7s', 'J6s', 'J5s', 'J4s', 'J3s', 'J2s',
        'T9s', 'T8s', 'T7s', 'T6s', 'T5s', 'T4s', 'T3s', 'T2s',
        '98s', '97s', '96s', '95s', '94s', '93s', '92s',
        '87s', '86s', '85s', '84s', '83s', '82s',
        '76s', '75s', '74s', '73s', '72s',
        '65s', '64s', '63s', '62s',
        '54s', '53s', '52s',
        '43s', '42s', '32s',
        # All offsuit aces (always defend vs wide SB range)
        'AKo', 'AQo', 'AJo', 'ATo', 'A9o', 'A8o', 'A7o', 'A6o', 'A5o', 'A4o', 'A3o', 'A2o',
        # Offsuit broadways and connected hands (profitable vs SB's wide range)
        'KQo', 'KJo', 'KTo', 'K9o', 'K8o', 'K7o',
        'QJo', 'QTo', 'Q9o', 'Q8o',
        'JTo', 'J9o', 'J8o',
        'T9o', 'T8o',
        '98o', '97o',
        '87o', '86o',
        '76o', '75o',
        '65o', '64o',
        '54o',
    }
    # Marginal hands - either action (call or fold) can be correct vs SB steal
    _BW_BB_MARGINAL = {
        'K6o', 'K5o', 'K4o', 'K3o', 'K2o',
        'Q7o', 'Q6o', 'Q5o', 'Q4o', 'Q3o', 'Q2o',
        'J7o', 'J6o', 'J5o', 'J4o', 'J3o', 'J2o',
        'T7o', 'T6o', 'T5o', 'T4o', 'T3o', 'T2o',
        '96o', '95o', '94o', '93o', '92o',
        '85o', '84o', '83o', '82o',
        '74o', '73o', '72o',
        '63o', '62o',
        '53o', '52o',
        '43o', '42o', '32o',
    }

    # ── Bounty Tournament Range Data (from RegLife Bounty PDFs) ─────────────
    # Bounty-adjusted ranges: wider calling/shoving ranges due to bounty value overlay.
    # Winning a bounty adds significant EV, making normally marginal spots profitable.

    # Tier 1: always profitable in bounty spots (strong hands + bounty premium).
    _BOUNTY_TIER1 = {
        # All pairs: set mining and pair value plus bounty overlay
        'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', '55', '44', '33', '22',
        # All suited aces: extra equity from flush potential
        'AKs', 'AQs', 'AJs', 'ATs', 'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
        # Suited broadways and medium kings
        'KQs', 'KJs', 'KTs', 'K9s', 'K8s',
        'QJs', 'QTs', 'Q9s',
        'JTs', 'J9s',
        'T9s', 'T8s',
        '98s', '87s', '76s',
        # Strong offsuit hands
        'AKo', 'AQo', 'AJo', 'ATo', 'A9o', 'A8o',
        'KQo', 'KJo', 'KTo',
        'QJo',
    }
    # Tier 2: marginal hands made profitable specifically by bounty overlay.
    _BOUNTY_TIER2 = {
        # Weak suited kings and medium queens
        'K7s', 'K6s', 'K5s', 'K4s', 'K3s', 'K2s',
        'Q8s', 'Q7s', 'J8s', 'J7s',
        'T7s', '97s', '86s', '75s', '65s', '64s', '54s',
        # Medium offsuit hands
        'A7o', 'A6o', 'A5o', 'A4o', 'A3o', 'A2o',
        'K9o', 'K8o',
        'QTo', 'Q9o',
        'JTo', 'J9o',
        'T9o', '98o', '87o',
    }

    def __init__(self, repo: Repository):
        self.repo = repo
        self._lessons = {}  # lesson_id -> lesson dict
        self._load_lessons()

    def _load_lessons(self):
        """Load lesson catalog keyed by sort_order (which equals lesson_id)."""
        for lesson in self.repo.get_lessons():
            self._lessons[lesson['lesson_id']] = lesson

    def _lesson_id_by_sort(self, sort_order: int) -> Optional[int]:
        """Get lesson_id for a given sort_order."""
        for lid, lesson in self._lessons.items():
            if lesson['sort_order'] == sort_order:
                return lid
        return None

    def classify_hand(self, hand: dict, actions: list[dict]) -> list[LessonMatch]:
        """Classify a single hand into matching lessons.

        Args:
            hand: dict with hand_id, hero_position, hero_cards, etc.
            actions: list of action dicts for this hand, ordered by street/sequence.

        Returns:
            list of LessonMatch objects.
        """
        matches = []
        hand_id = hand['hand_id']

        # Group actions by street
        by_street = defaultdict(list)
        for a in actions:
            by_street[a['street']].append(a)

        preflop = by_street.get('preflop', [])
        flop_actions = by_street.get('flop', [])
        turn_actions = by_street.get('turn', [])
        river_actions = by_street.get('river', [])

        hero_pos = (hand.get('hero_position') or '').upper()
        hero_stack_bb = self._stack_in_bb(hand)
        is_tournament = hand.get('game_type') == 'tournament'
        has_flop = bool(hand.get('board_flop'))
        has_turn = bool(hand.get('board_turn'))
        has_river = bool(hand.get('board_river'))

        # Preflop analysis
        pf = self._analyze_preflop(preflop, hero_pos)

        # --- Preflop Lessons ---

        # 1: RFI (Raise First In)
        if pf['hero_is_rfi']:
            m = self._match(hand_id, 1, 'preflop')
            m.executed_correctly = self._eval_rfi(hand, pf)
            matches.append(m)

        # 2: Flat / 3-Bet
        if pf['hero_flats'] or pf['hero_3bets']:
            m = self._match(hand_id, 2, 'preflop')
            m.executed_correctly = self._eval_flat_3bet(hand, pf)
            matches.append(m)

        # 3: Reaction vs 3-Bet
        if pf['hero_faces_3bet']:
            m = self._match(hand_id, 3, 'preflop')
            m.executed_correctly = self._eval_reaction_vs_3bet(hand, pf)
            matches.append(m)

        # 4: Open Shove cEV 10BB
        if pf['hero_open_shoves'] and hero_stack_bb is not None and hero_stack_bb <= 12:
            m = self._match(hand_id, 4, 'preflop')
            m.executed_correctly = self._eval_open_shove(hand, pf)
            matches.append(m)

        # 5: Squeeze
        if pf['hero_squeezes']:
            m = self._match(hand_id, 5, 'preflop')
            m.executed_correctly = self._eval_squeeze(hand, pf)
            matches.append(m)

        # 6: BB Pré-Flop
        if hero_pos == 'BB' and preflop:
            m = self._match(hand_id, 6, 'preflop')
            m.executed_correctly = self._eval_bb_preflop(hand, pf)
            matches.append(m)

        # 7: Blind War SB vs BB
        if hero_pos == 'SB' and pf['is_blind_war']:
            m = self._match(hand_id, 7, 'preflop')
            m.executed_correctly = self._eval_sb_vs_bb(hand, pf)
            matches.append(m)

        # 8: Multiway BB (also catches incorrect folds of strong hands)
        if hero_pos == 'BB' and pf['is_multiway']:
            m = self._match(hand_id, 8, 'preflop')
            m.executed_correctly = self._eval_multiway_bb(hand, pf)
            matches.append(m)

        # 9: Blind War BB vs SB
        if hero_pos == 'BB' and pf['is_blind_war_bb_vs_sb']:
            m = self._match(hand_id, 9, 'preflop')
            m.executed_correctly = self._eval_bb_vs_sb(hand, pf)
            matches.append(m)

        # --- Postflop Lessons ---
        if has_flop:
            pf_agg = pf['hero_is_preflop_aggressor']

            # 10: Introdução ao Pós-Flop
            m = self._match(hand_id, 10, 'flop')
            m.executed_correctly = 1 if hand.get('net', 0) >= 0 else 0
            m.confidence = 0.7
            matches.append(m)

            # 11: Introdução ao MDA
            if has_turn or has_river:
                m = self._match(hand_id, 11, 'flop')
                m.confidence = 0.6
                matches.append(m)

            # 12: Pós-Flop Avançado
            if has_turn and has_river:
                m = self._match(hand_id, 12, 'flop')
                m.confidence = 0.5
                matches.append(m)

            # Postflop action analysis
            flop_a = self._analyze_street_actions(flop_actions)
            turn_a = self._analyze_street_actions(turn_actions)
            river_a = self._analyze_street_actions(river_actions)

            hero_ip = self._is_hero_ip(hero_pos, preflop)

            # 13: C-Bet Flop IP
            if pf_agg and flop_a['hero_bets'] and hero_ip:
                m = self._match(hand_id, 13, 'flop')
                m.executed_correctly = self._eval_cbet_flop_ip(hand, flop_a)
                matches.append(m)

            # 14: C-Bet OOP
            if pf_agg and flop_a['hero_bets'] and not hero_ip:
                m = self._match(hand_id, 14, 'flop')
                m.executed_correctly = self._eval_cbet_flop_oop(hand, flop_a)
                matches.append(m)

            # 15: C-Bet Turn
            if pf_agg and has_turn and turn_a['hero_bets']:
                m = self._match(hand_id, 15, 'turn')
                m.executed_correctly = self._eval_cbet(turn_a)
                matches.append(m)

            # 16: C-Bet River
            if pf_agg and has_river and river_a['hero_bets']:
                m = self._match(hand_id, 16, 'river')
                m.executed_correctly = self._eval_cbet(river_a)
                matches.append(m)

            # 17: Delayed C-Bet
            if pf_agg and flop_a['hero_checks'] and has_turn and turn_a['hero_bets']:
                m = self._match(hand_id, 17, 'turn')
                m.executed_correctly = 1  # executed delayed cbet
                matches.append(m)

            # 18: BB vs C-Bet OOP
            if hero_pos == 'BB' and not hero_ip and flop_a['villain_bets_first']:
                m = self._match(hand_id, 18, 'flop')
                m.executed_correctly = self._eval_bb_vs_cbet(hand, flop_a)
                matches.append(m)

            # 19: Enfrentando Check-Raise
            if flop_a['hero_faces_checkraise'] or turn_a.get('hero_faces_checkraise'):
                street = 'flop' if flop_a['hero_faces_checkraise'] else 'turn'
                active_a = flop_a if flop_a['hero_faces_checkraise'] else turn_a
                m = self._match(hand_id, 19, street)
                m.executed_correctly = self._eval_facing_checkraise(hand, active_a)
                matches.append(m)

            # 20: Pós-Flop IP enfrentando C-Bet BTN
            if hero_ip and flop_a['villain_bets_first']:
                m = self._match(hand_id, 20, 'flop')
                m.executed_correctly = self._eval_ip_vs_cbet(hand, flop_a)
                matches.append(m)

            # 21: Bet vs Missed Bet
            if self._detect_bet_vs_missed(flop_a, turn_a, pf_agg):
                street = 'turn' if turn_a.get('hero_bets') else 'flop'
                m = self._match(hand_id, 21, street)
                m.executed_correctly = 1  # exploited missed bet
                matches.append(m)

            # 22: Probe do BB
            if hero_pos == 'BB' and not pf_agg and has_turn:
                if flop_a.get('villain_checks_back', False) and turn_a['hero_bets']:
                    m = self._match(hand_id, 22, 'turn')
                    m.executed_correctly = 1
                    matches.append(m)

            # 23: 3-Betted Pots Pós-Flop
            if pf['is_3bet_pot']:
                m = self._match(hand_id, 23, 'flop')
                m.executed_correctly = self._eval_3bet_pot_postflop(hand, flop_a, pf)
                matches.append(m)

        # --- Torneios Lessons ---
        if is_tournament and hand.get('tournament_id'):
            t_info = self.repo.get_tournament_info(hand['tournament_id'])
            is_bounty = t_info and t_info.get('is_bounty')

            # 24: Intro Torneios Bounty
            if is_bounty:
                m = self._match(hand_id, 24, 'preflop')
                m.executed_correctly = self._eval_bounty_intro(hand, pf)
                matches.append(m)

            # 25: Bounty Ranges Práticos
            if is_bounty and preflop:
                m = self._match(hand_id, 25, 'preflop')
                m.executed_correctly = self._eval_bounty_ranges(hand, pf)
                matches.append(m)

        return matches

    def classify_all(self) -> dict:
        """Classify all hands in the database.

        Returns:
            dict with keys: total_hands, classified_hands, total_links,
            lessons_matched (count of distinct lessons with matches).
        """
        hands = self.repo.get_all_hands_for_classification()
        all_actions = self.repo.get_all_actions_for_classification()

        # Group actions by hand_id
        actions_by_hand = defaultdict(list)
        for action in all_actions:
            actions_by_hand[action['hand_id']].append(action)

        # Clear existing classifications
        self.repo.clear_hand_lessons()

        all_links = []
        classified_hands = set()
        matched_lessons = set()

        for hand in hands:
            hand_actions = actions_by_hand.get(hand['hand_id'], [])
            if not hand_actions:
                continue

            matches = self.classify_hand(hand, hand_actions)
            for m in matches:
                lid = self._resolve_lesson_id(m.lesson_id)
                if lid is None:
                    continue
                all_links.append((
                    m.hand_id, lid, m.street,
                    m.executed_correctly, m.confidence, m.notes,
                ))
                classified_hands.add(m.hand_id)
                matched_lessons.add(lid)

        inserted = 0
        if all_links:
            inserted = self.repo.bulk_link_hand_lessons(all_links)

        return {
            'total_hands': len(hands),
            'classified_hands': len(classified_hands),
            'total_links': inserted,
            'lessons_matched': len(matched_lessons),
        }

    # ── Helper: create LessonMatch by sort_order ─────────────────────

    def _match(self, hand_id: str, sort_order: int,
               street: Optional[str] = None) -> LessonMatch:
        """Create a LessonMatch using sort_order as a proxy for lesson_id."""
        return LessonMatch(
            hand_id=hand_id,
            lesson_id=sort_order,  # resolved later via _resolve_lesson_id
            street=street,
        )

    def _resolve_lesson_id(self, sort_order: int) -> Optional[int]:
        """Resolve sort_order to actual lesson_id."""
        lid = self._lesson_id_by_sort(sort_order)
        return lid

    # ── Preflop Analysis ─────────────────────────────────────────────

    def _analyze_preflop(self, actions: list[dict], hero_pos: str) -> dict:
        """Analyze preflop action sequence to detect patterns."""
        result = {
            'hero_is_rfi': False,
            'hero_flats': False,
            'hero_3bets': False,
            'hero_faces_3bet': False,
            'hero_open_shoves': False,
            'hero_squeezes': False,
            'hero_folds_preflop': False,
            'hero_is_preflop_aggressor': False,
            'is_blind_war': False,
            'is_blind_war_bb_vs_sb': False,
            'is_multiway': False,
            'is_3bet_pot': False,
            'hero_action': None,
            'hero_raise_amount': 0,
            'open_raiser_pos': None,
            'callers_before_hero': 0,
        }

        if not actions:
            return result

        raises = []
        calls_before_hero = 0
        hero_acted = False
        first_raise_seen = False
        second_raise_seen = False
        open_raiser_pos = None
        players_in = set()
        hero_last_action = None

        for a in actions:
            player = a.get('player', '')
            action = a.get('action_type', '').lower()
            is_hero = a.get('is_hero', 0)

            if action == 'fold':
                if is_hero:
                    result['hero_folds_preflop'] = True
                    hero_last_action = 'fold'
                    # Hero faces 3-bet: hero opened, then someone re-raised, hero folds
                    if result['hero_is_rfi'] and second_raise_seen and not result['hero_3bets']:
                        result['hero_faces_3bet'] = True
                continue

            if action in ('call', 'raise', 'bet', 'all-in'):
                players_in.add(player)

            if action in ('raise', 'bet', 'all-in') and not first_raise_seen:
                first_raise_seen = True
                open_raiser_pos = a.get('position', '')
                if is_hero:
                    result['hero_is_rfi'] = True
                    result['hero_is_preflop_aggressor'] = True
                    result['hero_raise_amount'] = a.get('amount', 0)
                    if action == 'all-in':
                        result['hero_open_shoves'] = True
                raises.append(a)
            elif action in ('raise', 'all-in') and first_raise_seen and not second_raise_seen:
                second_raise_seen = True
                result['is_3bet_pot'] = True
                if is_hero:
                    if calls_before_hero > 0:
                        result['hero_squeezes'] = True
                    else:
                        result['hero_3bets'] = True
                    result['hero_is_preflop_aggressor'] = True
                raises.append(a)
            elif action in ('raise', 'all-in') and second_raise_seen:
                if is_hero:
                    result['hero_is_preflop_aggressor'] = True
                raises.append(a)

            if action == 'call' and not is_hero and first_raise_seen:
                if not hero_acted:
                    calls_before_hero += 1

            if is_hero:
                hero_acted = True
                hero_last_action = action
                if action == 'fold':
                    result['hero_folds_preflop'] = True
                elif action == 'call' and first_raise_seen:
                    result['hero_flats'] = True
                    result['callers_before_hero'] = calls_before_hero

            # Hero faces 3-bet: hero opened, then someone re-raised
            if is_hero and result['hero_is_rfi'] and second_raise_seen and not result['hero_3bets']:
                result['hero_faces_3bet'] = True

        result['hero_action'] = hero_last_action
        result['open_raiser_pos'] = open_raiser_pos

        # Blind war: folds to SB, SB raises, only BB left
        if open_raiser_pos and open_raiser_pos.upper() == 'SB':
            non_blind_actors = [a for a in actions
                                if a.get('position', '').upper() not in ('SB', 'BB', '')
                                and a.get('action_type', '').lower() != 'fold']
            if not non_blind_actors:
                result['is_blind_war'] = True
                if hero_pos == 'BB':
                    result['is_blind_war_bb_vs_sb'] = True

        # Multiway: 3+ players in the pot
        if len(players_in) >= 3:
            result['is_multiway'] = True

        return result

    # ── Street Action Analysis ───────────────────────────────────────

    def _analyze_street_actions(self, actions: list[dict]) -> dict:
        """Analyze actions on a single postflop street."""
        result = {
            'hero_bets': False,
            'hero_checks': False,
            'hero_raises': False,
            'hero_calls': False,
            'hero_folds': False,
            'villain_bets_first': False,
            'villain_checks_back': False,
            'hero_faces_checkraise': False,
            'hero_bet_amount': 0,
        }

        if not actions:
            return result

        first_bet_seen = False
        hero_bet_before_raise = False

        for a in actions:
            action = a.get('action_type', '').lower()
            is_hero = a.get('is_hero', 0)

            if is_hero:
                if action in ('bet', 'raise', 'all-in'):
                    if action == 'bet' or (action in ('raise', 'all-in') and not first_bet_seen):
                        result['hero_bets'] = True
                        result['hero_bet_amount'] = a.get('amount', 0)
                        hero_bet_before_raise = True
                    if action in ('raise', 'all-in'):
                        result['hero_raises'] = True
                elif action == 'check':
                    result['hero_checks'] = True
                elif action == 'call':
                    result['hero_calls'] = True
                elif action == 'fold':
                    result['hero_folds'] = True
            else:
                if action in ('bet', 'raise', 'all-in'):
                    if not first_bet_seen and not result['hero_bets']:
                        result['villain_bets_first'] = True
                    # Check-raise detection: hero bet, then villain raises
                    if hero_bet_before_raise and action in ('raise', 'all-in'):
                        result['hero_faces_checkraise'] = True
                    first_bet_seen = True
                elif action == 'check' and not result['hero_bets'] and not first_bet_seen:
                    # Villain checks (potential check-back)
                    pass

        # Villain checks back: no bets at all on street, and hero checked
        if not first_bet_seen and not result['hero_bets'] and result['hero_checks']:
            result['villain_checks_back'] = True
        # Also: hero is OOP, checks, villain checks behind
        if result['hero_checks'] and not result['hero_bets'] and not first_bet_seen:
            result['villain_checks_back'] = True

        return result

    # ── Position helpers ─────────────────────────────────────────────

    def _is_hero_ip(self, hero_pos: str, preflop_actions: list[dict]) -> bool:
        """Determine if hero is in position (acts last postflop)."""
        if hero_pos in ('BTN', 'CO'):
            return True
        if hero_pos in ('SB', 'BB'):
            return False
        # In multiway, approximate based on position
        return hero_pos in ('BTN', 'CO', 'HJ')

    def _stack_in_bb(self, hand: dict) -> Optional[float]:
        """Calculate hero stack in BB."""
        stack = hand.get('hero_stack')
        bb = hand.get('blinds_bb')
        if stack and bb and bb > 0:
            return stack / bb
        return None

    # ── Execution Evaluation ─────────────────────────────────────────

    def _hand_notation(self, hero_cards: str) -> Optional[str]:
        """Convert 'Ah Kd' → 'AKo', 'Ah Kh' → 'AKs', 'Ad Ah' → 'AA'."""
        if not hero_cards or not hero_cards.strip():
            return None
        parts = hero_cards.strip().split()
        if len(parts) != 2:
            return None
        c1, c2 = parts[0].strip(), parts[1].strip()
        if len(c1) < 2 or len(c2) < 2:
            return None
        r1, s1 = c1[:-1].upper(), c1[-1].lower()
        r2, s2 = c2[:-1].upper(), c2[-1].lower()
        if r1 == '10':
            r1 = 'T'
        if r2 == '10':
            r2 = 'T'
        if r1 not in self._RANK_ORDER or r2 not in self._RANK_ORDER:
            return None
        i1 = self._RANK_ORDER.index(r1)
        i2 = self._RANK_ORDER.index(r2)
        if i1 < i2:
            r1, r2 = r2, r1
        if r1 == r2:
            return f'{r1}{r2}'
        suffix = 's' if s1 == s2 else 'o'
        return f'{r1}{r2}{suffix}'

    def _rfi_hand_tier(self, notation: str) -> int:
        """Return RFI tier (1-5) for a hand notation. Lower = stronger."""
        if notation in self._RFI_TIER1:
            return 1
        if notation in self._RFI_TIER2:
            return 2
        if notation in self._RFI_TIER3:
            return 3
        if notation in self._RFI_TIER4:
            return 4
        return 5

    def _bb_hand_tier(self, notation: str) -> int:
        """Return BB defense tier (1-5) for a hand notation.

        Tier 1 = strongest (defend vs any opener including UTG).
        Tier 5 = trash (fold vs any raise).
        """
        if notation in self._BB_TIER1:
            return 1
        if notation in self._BB_TIER2:
            return 2
        if notation in self._BB_TIER3:
            return 3
        if notation in self._BB_TIER4:
            return 4
        return 5

    def _eval_rfi(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate RFI execution based on position, hand strength, and sizing.

        Based on RegLife 'Ranges de RFI em cEV' PDF:
        - Correct (1): Hand in range for position with standard sizing (2-2.5BB)
        - Partial (None): In range but wrong sizing, or marginal hand
        - Incorrect (0): Hand clearly too weak for position
        """
        hero_pos = (hand.get('hero_position') or '').upper()
        hero_cards = hand.get('hero_cards')

        # Check sizing: PDF recommends 2-2.5BB (cEV), cash games use up to 3BB
        sizing_ok = None
        raise_amount = pf.get('hero_raise_amount', 0)
        bb = hand.get('blinds_bb')
        if raise_amount and bb and bb > 0:
            sizing_bb = raise_amount / bb
            sizing_ok = 2.0 <= sizing_bb <= 3.0

        # Without hero cards, evaluate sizing only
        if not hero_cards:
            if sizing_ok is True:
                return 1
            if sizing_ok is False:
                return None
            return None

        notation = self._hand_notation(hero_cards)
        if not notation:
            return 1 if sizing_ok is not False else None

        hand_tier = self._rfi_hand_tier(notation)
        pos_tier = self._RFI_POS_MAX_TIER.get(hero_pos, 2)

        if hand_tier <= pos_tier:
            # Hand is in range for this position
            if sizing_ok is False:
                return None  # right hand, wrong sizing
            return 1
        elif hand_tier == pos_tier + 1:
            # Marginal hand for this position
            return None
        else:
            # Hand clearly too weak for position
            return 0

    def _flat_hand_tier(self, notation: str) -> int:
        """Return flat-call tier (1-4) for a hand notation. Lower = stronger."""
        if notation in self._FLAT_TIER1:
            return 1
        if notation in self._FLAT_TIER2:
            return 2
        if notation in self._FLAT_TIER3:
            return 3
        return 4  # not in any flat range

    def _3bet_hand_tier(self, notation: str) -> int:
        """Return 3-bet tier (1-5) for a hand notation. Lower = stronger."""
        if notation in self._3BET_TIER1:
            return 1
        if notation in self._3BET_TIER2:
            return 2
        if notation in self._3BET_TIER3:
            return 3
        if notation in self._3BET_TIER4:
            return 4
        return 5  # not in any 3-bet range

    def _squeeze_hand_tier(self, notation: str) -> int:
        """Return squeeze tier (1-3) for a hand notation. Lower = stronger."""
        if notation in self._SQUEEZE_TIER1:
            return 1
        if notation in self._SQUEEZE_TIER2:
            return 2
        return 3  # not in any squeeze range

    def _open_shove_hand_tier(self, notation: str) -> int:
        """Return open shove tier (1-5) for a hand notation. Lower = stronger."""
        if notation in self._OPEN_SHOVE_TIER1:
            return 1
        if notation in self._OPEN_SHOVE_TIER2:
            return 2
        if notation in self._OPEN_SHOVE_TIER3:
            return 3
        if notation in self._OPEN_SHOVE_TIER4:
            return 4
        return 5  # not in any open shove range

    def _bounty_hand_tier(self, notation: str) -> int:
        """Return bounty call tier (1-3) for a hand notation. Lower = stronger."""
        if notation in self._BOUNTY_TIER1:
            return 1
        if notation in self._BOUNTY_TIER2:
            return 2
        return 3  # not in any bounty range

    def _eval_flat_3bet(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate flat/3-bet execution based on position and hand ranges.

        Based on RegLife 'Ranges de Flat e 3-BET':
        - Correct (1): Hand in appropriate flat or 3-bet range for position.
        - Partial (None): Marginal hand (one tier outside range).
        - Incorrect (0): Hand clearly too weak to flat or 3-bet.
        """
        hero_cards = hand.get('hero_cards')
        hero_pos = (hand.get('hero_position') or '').upper()

        if not hero_cards:
            return 1  # action taken, can't evaluate hand quality

        notation = self._hand_notation(hero_cards)
        if not notation:
            return 1  # can't parse hand

        if pf['hero_3bets']:
            # Evaluate 3-bet range
            hand_tier = self._3bet_hand_tier(notation)
            pos_tier = self._3BET_POS_MAX_TIER.get(hero_pos, 2)
            if hand_tier <= pos_tier:
                return 1  # hand is in 3-bet range for position
            elif hand_tier == pos_tier + 1:
                return None  # marginal 3-bet
            else:
                return 0  # hand too weak to 3-bet

        if pf['hero_flats']:
            # Evaluate flat-call range
            hand_tier = self._flat_hand_tier(notation)
            pos_tier = self._FLAT_POS_MAX_TIER.get(hero_pos, 2)
            if hand_tier <= pos_tier:
                return 1  # hand is in flat range for position
            elif hand_tier == pos_tier + 1:
                return None  # marginal flat
            else:
                return 0  # hand too weak to flat

        return None

    def _eval_reaction_vs_3bet(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate reaction to 3-bet based on hand strength and ranges.

        Based on RegLife 'Ranges de reação vs 3-bet':
        - Correct (1): Continued with strong hand, folded trash, or 4-bet premium.
        - Partial (None): Marginal hand where both actions have similar EV.
        - Incorrect (0): Folded a clearly continuable hand, or called with trash.
        """
        hero_cards = hand.get('hero_cards')
        hero_folded = pf.get('hero_folds_preflop', False)

        if not hero_cards:
            return None  # can't evaluate without hand info

        notation = self._hand_notation(hero_cards)
        if not notation:
            return None

        if notation in self._VS3BET_CONTINUE:
            # Should always continue (call or 4-bet)
            return 0 if hero_folded else 1
        elif notation in self._VS3BET_MARGINAL:
            # Marginal: either action is defensible
            return None
        else:
            # Trash hand vs 3-bet: should fold
            return 1 if hero_folded else 0

    def _eval_squeeze(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate squeeze execution based on position and hand ranges.

        Based on RegLife 'SQUEEZE' PDF:
        - Correct (1): Hand in squeeze range for position.
        - Partial (None): Marginal hand (one tier outside range).
        - Incorrect (0): Hand clearly too weak to squeeze.
        """
        hero_cards = hand.get('hero_cards')
        hero_pos = (hand.get('hero_position') or '').upper()

        if not hero_cards:
            return 1  # squeezed without visible cards, assume correct

        notation = self._hand_notation(hero_cards)
        if not notation:
            return 1  # can't parse hand

        hand_tier = self._squeeze_hand_tier(notation)
        pos_tier = self._SQUEEZE_POS_MAX_TIER.get(hero_pos, 1)

        if hand_tier <= pos_tier:
            return 1  # hand is in squeeze range for position
        elif hand_tier == pos_tier + 1:
            return None  # marginal squeeze
        else:
            return 0  # hand too weak to squeeze

    def _eval_open_shove(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate open shove execution based on position and hand strength.

        Based on RegLife 'Ranges de Open Shove cEV 10BB':
        - Correct (1): Hand in open shove range for position at ≤10BB stack.
        - Partial (None): Marginal hand (one tier outside range) or 10-12BB stack.
        - Incorrect (0): Hand clearly too weak for position.
        """
        hero_cards = hand.get('hero_cards')
        hero_pos = (hand.get('hero_position') or '').upper()
        hero_stack_bb = self._stack_in_bb(hand)

        # Stack in marginal range (10-12BB): shoving may be suboptimal vs minraising
        if hero_stack_bb is not None and hero_stack_bb > 10:
            return None

        if not hero_cards:
            return 1  # can't evaluate hand quality, assume correct

        notation = self._hand_notation(hero_cards)
        if not notation:
            return 1  # can't parse hand, assume correct

        hand_tier = self._open_shove_hand_tier(notation)
        pos_tier = self._OPEN_SHOVE_POS_MAX_TIER.get(hero_pos, 2)

        if hand_tier <= pos_tier:
            return 1  # hand is in open shove range for position
        elif hand_tier == pos_tier + 1:
            return None  # marginal open shove (one tier outside range)
        else:
            return 0  # hand too weak to open shove from this position

    def _eval_bounty_intro(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate preflop play in introductory bounty tournament context.

        Based on RegLife 'Introdução aos Torneios Bounty':
        - This is a conceptual lesson; most situations are context-dependent.
        - Incorrect (0): folding a premium hand when a bounty is at stake.
        - Otherwise None: cannot evaluate nuanced bounty decisions without more context.
        """
        hero_cards = hand.get('hero_cards')
        hero_folded = pf.get('hero_folds_preflop', False)

        if not hero_cards:
            return None

        notation = self._hand_notation(hero_cards)
        if not notation:
            return None

        # Clear mistake: folding a premium hand when facing a bounty opportunity
        if hero_folded and notation in {'AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'}:
            return 0

        return None  # most bounty situations are context-dependent

    def _eval_bounty_ranges(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate preflop ranges in practical bounty tournament play.

        Based on RegLife 'Torneios Bounty - Ranges Práticos':
        - Correct (1): Hand in bounty-adjusted tier 1 range (clearly profitable).
        - Partial (None): Marginal hand in bounty tier 2 (context-dependent).
        - Incorrect (0): Hand too weak even with bounty overlay.
        """
        hero_cards = hand.get('hero_cards')

        if not hero_cards:
            return None  # can't evaluate without knowing the hand

        notation = self._hand_notation(hero_cards)
        if not notation:
            return None

        hand_tier = self._bounty_hand_tier(notation)
        if hand_tier == 1:
            return 1  # clearly profitable with bounty overlay
        elif hand_tier == 2:
            return None  # marginal, depends on bounty size and stack depth
        else:
            return 0  # too weak even with bounty overlay

    def _eval_bb_preflop(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate BB preflop play vs a single raise.

        Based on RegLife 'Jogando no Big Blind - Pré-Flop':
        - Correct (1): Defended strong hand for opener position, folded trash,
          or checked a free flop in a limped pot.
        - Partial (None): Marginal hand (one tier wider than opener's max tier);
          correct action depends on sizing and tendencies.
        - Incorrect (0): Folded a strong BB hand, or called/raised with trash.
        """
        hero_cards = hand.get('hero_cards')
        hero_folded = pf.get('hero_folds_preflop', False)
        open_raiser_pos = (pf.get('open_raiser_pos') or '').upper()

        # Limped pot (no open raise) or BB raised themselves (iso-raise):
        # checking/raising is standard play → mark as correct.
        if not open_raiser_pos or open_raiser_pos == 'BB':
            return 1 if not hero_folded else None

        # Cannot evaluate hand quality without hero cards.
        if not hero_cards:
            return None

        notation = self._hand_notation(hero_cards)
        if not notation:
            return None

        hand_tier = self._bb_hand_tier(notation)
        pos_tier = self._BB_POS_DEFEND_TIER.get(open_raiser_pos, 2)

        if hand_tier <= pos_tier:
            # Hand is in range for this opener: should defend.
            return 0 if hero_folded else 1
        elif hand_tier == pos_tier + 1 and hand_tier <= 4:
            # Marginal hand (one tier above opener's max, but not trash):
            # action is context-dependent.
            return None
        else:
            # Hand is too weak to defend vs this opener: should fold.
            return 1 if hero_folded else 0

    def _eval_sb_vs_bb(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate SB steal attempt in a blind war.

        Based on RegLife 'O Conceito de Blind War - SB vs BB':
        - SB should raise (never limp) with a wide range when only BB remains.
        - Correct (1): Raised with hand in SB steal range (RFI Tier 1-4 plus SB extras).
        - Partial (None): Raised with a borderline hand outside known ranges.
        - Incorrect (0): Raised with clear trash below the SB steal range.
        """
        # Detection requires SB to have raised (is_blind_war flag), so hero_is_rfi is True.
        hero_cards = hand.get('hero_cards')
        if not hero_cards:
            return 1  # raised without visible cards - execution assumed correct

        notation = self._hand_notation(hero_cards)
        if not notation:
            return 1  # raised, can't evaluate hand quality

        # Hand in standard BTN/SB RFI range (Tier 1-4): correct steal
        rfi_tier = self._rfi_hand_tier(notation)
        if rfi_tier <= 4:
            return 1

        # Hand in SB-specific steal extras (beyond BTN range): correct steal
        if notation in self._SB_WAR_EXTRA:
            return 1

        # Everything else is clear trash from SB perspective: raising is incorrect
        return 0

    def _eval_bb_vs_sb(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate BB defense in a blind war vs SB steal.

        Based on RegLife 'Blind War BB vs SB':
        - BB defends wider vs SB than vs any other position because:
          SB's range is wide, BB has positional advantage postflop, pot odds are good.
        - Correct (1): Defended with a clear defend hand, or folded clear trash.
        - Partial (None): Marginal hand (sizing/read dependent).
        - Incorrect (0): Folded a clearly defensible hand, or defended with trash.
        """
        hero_cards = hand.get('hero_cards')
        hero_folded = pf.get('hero_folds_preflop', False)

        if not hero_cards:
            return None  # cannot evaluate without hand information

        notation = self._hand_notation(hero_cards)
        if not notation:
            return None

        if notation in self._BW_BB_DEFEND:
            # Strong enough hand to defend vs wide SB range
            return 0 if hero_folded else 1
        elif notation in self._BW_BB_MARGINAL:
            # Borderline hand: fold or call both reasonable
            return None
        else:
            # Clear trash: folding is correct, defending is incorrect
            return 1 if hero_folded else 0

    def _eval_multiway_bb(self, hand: dict, pf: dict) -> Optional[int]:
        """Evaluate BB defense in multiway preflop situation.

        Based on RegLife 'Defesa Multiway do Big Blind Pré-Flop':
        - Correct (1): Defended with strong hand, or folded clear trash
        - Partial (None): Marginal hand (defense vs fold depends on pot odds/SPR)
        - Incorrect (0): Folded a strong multiway hand, or called with trash
        """
        hero_cards = hand.get('hero_cards')
        hero_folded = pf.get('hero_folds_preflop', False)

        if not hero_cards:
            return None  # cannot evaluate without knowing the hand

        notation = self._hand_notation(hero_cards)
        if not notation:
            return None

        if notation in self._MWBB_DEFEND:
            # Strong multiway hand: folding is a mistake
            if hero_folded:
                return 0  # incorrect fold
            return 1  # correct defense
        elif notation in self._MWBB_MARGINAL:
            # Marginal hand: either action could be correct
            return None
        else:
            # Trash hand: should fold even with good pot odds
            if hero_folded:
                return 1  # correct fold
            return 0  # incorrect defense with trash

    def _eval_cbet(self, street_analysis: dict) -> Optional[int]:
        """Evaluate c-bet execution."""
        return 1 if street_analysis['hero_bets'] else 0

    def _eval_facing_cbet(self, street_analysis: dict) -> Optional[int]:
        """Evaluate response to c-bet."""
        if street_analysis.get('hero_folds'):
            return None  # fold may be correct
        if street_analysis.get('hero_raises'):
            return 1  # raised = aggressive response
        if street_analysis.get('hero_calls'):
            return 1  # called = defended
        return None

    # ── Board Analysis Helpers ────────────────────────────────────────

    @classmethod
    def _parse_cards(cls, cards_str: str) -> list[tuple[str, str]]:
        """Parse 'Ah Kd 2c' → [('A','h'), ('K','d'), ('2','c')]."""
        result: list[tuple[str, str]] = []
        if not cards_str:
            return result
        for token in cards_str.split():
            if len(token) >= 2:
                rank = token[0].upper()
                suit = token[1].lower()
                if rank in cls._RANK_ORDER and suit in 'hdcs':
                    result.append((rank, suit))
        return result

    @classmethod
    def _board_texture(cls, board_flop: str) -> str:
        """Classify flop texture as 'dry', 'neutral', or 'wet'.

        Wet:     2+ same suit AND highly connected (span ≤ 4), or monotone.
        Neutral: 2+ same suit OR highly connected (but not both).
        Dry:     rainbow and disconnected.
        """
        cards = cls._parse_cards(board_flop)
        if len(cards) < 3:
            return 'neutral'

        suits = [c[1] for c in cards]
        ranks = [c[0] for c in cards]

        suit_counts: dict[str, int] = {}
        for s in suits:
            suit_counts[s] = suit_counts.get(s, 0) + 1
        two_suited = any(v >= 2 for v in suit_counts.values())

        rank_idxs = sorted(
            cls._RANK_ORDER.index(r) for r in ranks if r in cls._RANK_ORDER
        )
        if len(rank_idxs) < 2:
            return 'neutral'
        span = rank_idxs[-1] - rank_idxs[0]
        highly_connected = span <= 4

        if two_suited and highly_connected:
            return 'wet'
        if two_suited or highly_connected:
            return 'neutral'
        return 'dry'

    @classmethod
    def _hand_connects_board(cls, hero_cards: str,
                             board_flop: str) -> Optional[str]:
        """Evaluate how hero's hole cards connect with the flop.

        Returns:
            'strong': top pair + J+ kicker, two pair, overpair, set/trips
            'medium': top pair weak kicker, middle/bottom pair, underpair
            'draw':   flush draw (4-flush) or open-ended straight draw
            'weak':   overcards or no significant equity
            None:     cannot evaluate (missing cards)
        """
        hero = cls._parse_cards(hero_cards)
        board = cls._parse_cards(board_flop)

        if len(hero) < 2 or len(board) < 3:
            return None

        h_ranks = [c[0] for c in hero]
        h_suits = [c[1] for c in hero]
        b_ranks = [c[0] for c in board]
        b_suits = [c[1] for c in board]
        ro = cls._RANK_ORDER

        is_pocket_pair = h_ranks[0] == h_ranks[1]

        # Set: pocket pair + matching board card
        if is_pocket_pair and h_ranks[0] in b_ranks:
            return 'strong'

        b_rank_idxs = sorted(
            [ro.index(r) for r in b_ranks if r in ro], reverse=True
        )

        # Overpair / underpair
        if is_pocket_pair:
            h_idx = ro.index(h_ranks[0]) if h_ranks[0] in ro else -1
            if b_rank_idxs and h_idx > b_rank_idxs[0]:
                return 'strong'  # overpair
            return 'medium'  # underpair

        # Two pair: both hero cards hit different board ranks
        hits = [r for r in h_ranks if r in b_ranks]
        if len(hits) >= 2:
            return 'strong'

        if len(hits) == 1:
            hit_rank = hits[0]
            hit_idx = ro.index(hit_rank) if hit_rank in ro else -1
            other_h = [r for r in h_ranks if r != hit_rank]
            if hit_idx == b_rank_idxs[0]:  # top pair
                if other_h and ro.index(other_h[0]) >= ro.index('J'):
                    return 'strong'  # top pair + J+ kicker
                return 'medium'  # top pair weak kicker
            return 'medium'  # middle or bottom pair

        # No made pair — check draws
        suit_cnt: dict[str, int] = {}
        for s in h_suits + b_suits:
            suit_cnt[s] = suit_cnt.get(s, 0) + 1
        if any(v >= 4 for v in suit_cnt.values()):
            return 'draw'  # flush draw (4-flush among 5 cards)

        # Open-ended straight draw: 4 cards in a 5-rank window
        all_idxs = sorted(set(
            ro.index(r) for r in h_ranks + b_ranks if r in ro
        ))
        for i in range(len(all_idxs)):
            window = [x for x in all_idxs
                      if all_idxs[i] <= x <= all_idxs[i] + 4]
            if len(window) >= 4:
                return 'draw'

        return 'weak'

    def _eval_cbet_flop_ip(self, hand: dict,
                           flop_a: dict) -> Optional[int]:  # noqa: ARG002
        """Evaluate c-bet flop IP execution.

        Based on RegLife 'CBet Flop IP':
        - IP bets frequently: value and bluffs on dry boards are correct.
        - On wet boards, bluffing without equity is a mistake.
        - Correct (1): value/draw, or air on dry board.
        - Partial (None): air on neutral board (marginal bluff).
        - Incorrect (0): air on wet board (over-bluffing without equity).
        """
        board_flop = hand.get('board_flop')
        hero_cards = hand.get('hero_cards')

        if not hero_cards or not board_flop:
            return 1  # cannot evaluate, assume correct

        texture = self._board_texture(board_flop)
        strength = self._hand_connects_board(hero_cards, board_flop)

        if strength is None:
            return 1

        if strength in ('strong', 'medium', 'draw'):
            return 1  # value or semi-bluff: correct regardless of texture

        # strength == 'weak' (air)
        if texture == 'dry':
            return 1   # bluffing dry boards IP is fine
        if texture == 'neutral':
            return None  # marginal
        return 0  # air on wet board: over-bluffing

    def _eval_cbet_flop_oop(self, hand: dict,
                            flop_a: dict) -> Optional[int]:  # noqa: ARG002
        """Evaluate c-bet flop OOP execution.

        Based on RegLife 'CBet Flop OOP':
        - OOP cbets with value hands and semi-bluffs: correct.
        - OOP bluffing air is generally a mistake (vulnerable position).
        - Correct (1): value or draw.
        - Partial (None): air on dry board (occasionally correct OOP).
        - Incorrect (0): air on wet or neutral board.
        """
        board_flop = hand.get('board_flop')
        hero_cards = hand.get('hero_cards')

        if not hero_cards or not board_flop:
            return 1  # cannot evaluate, assume correct

        texture = self._board_texture(board_flop)
        strength = self._hand_connects_board(hero_cards, board_flop)

        if strength is None:
            return 1

        if strength in ('strong', 'medium', 'draw'):
            return 1  # value or semi-bluff OOP: correct

        # strength == 'weak' (air)
        if texture == 'dry':
            return None  # marginally acceptable OOP on dry boards
        return 0  # air OOP on wet/neutral: incorrect

    def _eval_bb_vs_cbet(self, hand: dict, flop_a: dict) -> Optional[int]:
        """Evaluate BB response to a flop c-bet (OOP).

        Based on RegLife 'BB vs CBet OOP':
        - Defend (call/raise) with made hands and draws: correct.
        - Fold with made hands or draws: incorrect.
        - Fold with air: correct.
        - Call/raise with air: incorrect.
        - Draws: folding is marginal (depends on sizing/odds).
        """
        board_flop = hand.get('board_flop')
        hero_cards = hand.get('hero_cards')

        hero_folds = flop_a.get('hero_folds', False)

        if not hero_cards or not board_flop:
            if hero_folds:
                return None  # fold may be correct, cannot evaluate
            return 1

        strength = self._hand_connects_board(hero_cards, board_flop)

        if strength is None:
            return None if hero_folds else 1

        if strength in ('strong', 'medium'):
            return 0 if hero_folds else 1  # should defend made hands

        if strength == 'draw':
            if hero_folds:
                return None  # folding a draw is sizing-dependent
            return 1  # defending draws is correct

        # strength == 'weak' (air)
        return 1 if hero_folds else 0

    def _eval_ip_vs_cbet(self, hand: dict, flop_a: dict) -> Optional[int]:
        """Evaluate IP response to villain's flop c-bet.

        Based on RegLife 'Pós-Flop IP - Enfrentando C-Bet':
        - IP should defend wide vs c-bets (position is an asset).
        - Folding made hands (strong/medium) IP is a clear mistake.
        - Draws are profitable to defend (call or raise as semi-bluff).
        - With air: folding is fine; floating or bluff-raising can be correct.
        - Correct (1): defend with made hand or draw; fold or raise with air.
        - Marginal (None): float (call) with air; fold a draw (sizing-dep).
        - Incorrect (0): fold made hand or medium hand IP.
        """
        board_flop = hand.get('board_flop')
        hero_cards = hand.get('hero_cards')

        hero_folds = flop_a.get('hero_folds', False)
        hero_raises = flop_a.get('hero_raises', False)

        if not hero_cards or not board_flop:
            if hero_folds:
                return None  # cannot evaluate, fold may be correct
            return 1  # defending is generally right IP

        strength = self._hand_connects_board(hero_cards, board_flop)

        if strength is None:
            return None if hero_folds else 1

        if strength in ('strong', 'medium'):
            return 0 if hero_folds else 1  # never fold made hands IP

        if strength == 'draw':
            if hero_folds:
                return None  # sizing-dependent
            return 1  # defending draws IP (call or semi-bluff raise)

        # strength == 'weak' (air)
        if hero_folds:
            return 1  # correct to give up with nothing
        if hero_raises:
            return 1  # bluff-raise IP is a sound play
        return None  # floating (calling) with air IP is marginal

    def _eval_facing_checkraise(self, hand: dict,
                                street_a: dict) -> Optional[int]:
        """Evaluate hero's response when facing a check-raise.

        Based on RegLife 'Enfrentando o Check-Raise':
        - Check-raises represent strength: weak hands should fold.
        - Strong made hands should continue (call or 3-bet).
        - Medium hands: calling is usually correct, folding is marginal.
        - Draws: defending is correct (equity); folding is sizing-dependent.
        - Correct (1): fold air; defend made hands or draws.
        - Marginal (None): fold medium/draw (sizing/stack dep); call air.
        - Incorrect (0): fold strong hand; call/raise with air.
        """
        board_flop = hand.get('board_flop')
        hero_cards = hand.get('hero_cards')

        hero_folds = street_a.get('hero_folds', False)
        hero_raises = street_a.get('hero_raises', False)

        if not hero_cards or not board_flop:
            if hero_folds:
                return None  # cannot evaluate
            return 1  # defending is generally fine

        strength = self._hand_connects_board(hero_cards, board_flop)

        if strength is None:
            return None

        if strength == 'strong':
            return 0 if hero_folds else 1  # must not fold premium hands

        if strength == 'medium':
            if hero_folds:
                return None  # folding medium vs c/r can be correct
            if hero_raises:
                return None  # 3-betting a medium hand is marginal
            return 1  # calling with medium hand: correct

        if strength == 'draw':
            if hero_folds:
                return None  # depends on sizing and pot odds
            return 1  # defending draws vs check-raise: correct

        # strength == 'weak' (air)
        return 1 if hero_folds else 0  # fold air vs c/r; defending is wrong

    def _eval_3bet_pot_postflop(self, hand: dict, flop_a: dict,
                                pf: dict) -> Optional[int]:
        """Evaluate postflop play in a 3-bet pot.

        Based on RegLife '3-Betted Pots Pós-Flop':
        - SPR is low (~2-3): made hands should not fold to a single bet.
        - PFA should c-bet their range (value and bluffs).
        - Caller: defend made hands and draws; fold air vs c-bet.
        - Correct (1): defend made hands/draws; PFA c-bets or folds air.
        - Marginal (None): fold draw (SPR/sizing dep); check back as PFA.
        - Incorrect (0): fold made hand; caller raises air; check-fold PFA.
        """
        board_flop = hand.get('board_flop')
        hero_cards = hand.get('hero_cards')
        # hero_3bets/hero_squeezes = hero made the last preflop raise (PFA into flop)
        # hero_is_preflop_aggressor stays True even if hero opened then called a 3-bet
        pf_agg = pf.get('hero_3bets', False) or pf.get('hero_squeezes', False)

        hero_folds = flop_a.get('hero_folds', False)
        hero_bets = flop_a.get('hero_bets', False)
        hero_raises = flop_a.get('hero_raises', False)

        if not hero_cards or not board_flop:
            if hero_folds:
                return None  # cannot evaluate
            return 1

        strength = self._hand_connects_board(hero_cards, board_flop)

        if strength is None:
            return None

        if strength in ('strong', 'medium'):
            return 0 if hero_folds else 1  # never fold made hands 3-bet pot

        if strength == 'draw':
            if hero_folds:
                return None  # depends on SPR and bet sizing
            return 1  # playing draws aggressively: correct

        # strength == 'weak' (air)
        if pf_agg:
            # PFA should c-bet with air (protection + fold equity)
            if hero_bets:
                return 1  # c-bet air in 3-bet pot: correct
            if hero_folds:
                return None  # check-fold air as PFA: marginal
            return None  # checking air back as PFA: marginal
        else:
            # Caller with air: fold vs c-bet
            if hero_folds:
                return 1  # correct to fold air as caller
            if hero_raises:
                return 0  # raising with air as caller: incorrect
            return None  # floating with air as caller: marginal

    # ── Advanced Detection ───────────────────────────────────────────

    def _detect_bet_vs_missed(self, flop_a: dict, turn_a: dict,
                              hero_is_pfa: bool) -> bool:
        """Detect Bet vs Missed Bet pattern.

        Villain was aggressor (or had initiative), checks, hero bets.
        """
        if not hero_is_pfa:
            # Hero is not PFA, villain checked, hero bets = exploitation
            if flop_a.get('villain_checks_back') and turn_a.get('hero_bets'):
                return True
            # Villain bet flop but checked turn, hero bets turn
            if flop_a.get('villain_bets_first') and turn_a.get('hero_bets') and not turn_a.get('villain_bets_first'):
                return True
        return False
