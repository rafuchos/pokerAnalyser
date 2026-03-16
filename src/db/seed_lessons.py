"""Seed data for RegLife poker lessons catalog."""

from datetime import datetime

# 23 RegLife lessons organized by category and subcategory
REGLIFE_LESSONS = [
    # ── Preflop: Ranges ──────────────────────────────────────────────
    {
        'title': 'Ranges de RFI em cEV',
        'category': 'Preflop',
        'subcategory': 'Ranges',
        'pdf_filename': 'Reg Life - Ranges de RFI em cEV.pdf',
        'description': 'Ranges de Raise First In baseados em chip EV para cada posição.',
        'sort_order': 1,
    },
    {
        'title': 'Ranges de Flat e 3-BET',
        'category': 'Preflop',
        'subcategory': 'Ranges',
        'pdf_filename': 'RegLife-RangesdeFlate3-BET.pdf',
        'description': 'Construção de ranges de flat call e 3-bet por posição.',
        'sort_order': 2,
    },
    {
        'title': 'Ranges de Reação vs 3-Bet',
        'category': 'Preflop',
        'subcategory': 'Ranges',
        'pdf_filename': 'RegLife-Rangesdereacaovs3-bet.pdf',
        'description': 'Como reagir quando enfrentar 3-bet: fold, call ou 4-bet.',
        'sort_order': 3,
    },
    {
        'title': 'Ranges de Open Shove cEV 10BB',
        'category': 'Preflop',
        'subcategory': 'Ranges',
        'pdf_filename': 'RegLife-RangesdeopenshovecEV10BB.pdf',
        'description': 'Ranges de open shove com 10BB ou menos baseados em cEV.',
        'sort_order': 4,
    },
    {
        'title': 'Squeeze',
        'category': 'Preflop',
        'subcategory': 'Ranges',
        'pdf_filename': 'RegLife-SQUEEZE.pdf',
        'description': 'Conceito e ranges de squeeze preflop.',
        'sort_order': 5,
    },
    # ── Preflop: Blinds ──────────────────────────────────────────────
    {
        'title': 'Jogando no Big Blind - Pré-Flop',
        'category': 'Preflop',
        'subcategory': 'Blinds',
        'pdf_filename': 'RegLife-JogandonoBigBlind-Pre-Flop.pdf',
        'description': 'Defesa e estratégias de jogo do Big Blind no pré-flop.',
        'sort_order': 6,
    },
    {
        'title': 'O Conceito de Blind War - SB vs BB',
        'category': 'Preflop',
        'subcategory': 'Blinds',
        'pdf_filename': 'RegLife-OConceitodeBlindWar-SBvsBB (1).pdf',
        'description': 'Estratégia de guerra de blinds entre Small Blind e Big Blind.',
        'sort_order': 7,
    },
    {
        'title': 'Defesa Multiway do Big Blind Pré-Flop',
        'category': 'Preflop',
        'subcategory': 'Blinds',
        'pdf_filename': 'RegLife-DEFESAMULTIWAYDOBIGBLINDPRE-FLOP (1).pdf',
        'description': 'Ajustes de defesa do BB em potes multiway pré-flop.',
        'sort_order': 8,
    },
    {
        'title': 'Blind War - BB vs SB',
        'category': 'Preflop',
        'subcategory': 'Blinds',
        'pdf_filename': 'RegLife-BLINDWARBBVSSB.pdf',
        'description': 'Estratégia do Big Blind enfrentando steal do Small Blind.',
        'sort_order': 9,
    },
    # ── Postflop: Fundamentos ────────────────────────────────────────
    {
        'title': 'Pós-Flop Avançado',
        'category': 'Postflop',
        'subcategory': 'Fundamentos',
        'pdf_filename': 'RegLife-POS-FLOPAVANCADO.pdf',
        'description': 'Conceitos avançados de jogo pós-flop: polarização, ranges, bloqueadores.',
        'sort_order': 10,
    },
    # ── Postflop: C-Bet ──────────────────────────────────────────────
    {
        'title': 'C-Bet Flop em Posição',
        'category': 'Postflop',
        'subcategory': 'C-Bet',
        'pdf_filename': 'RegLife-CBETFLOPEMPOSICAO (3).pdf',
        'description': 'Estratégia de continuation bet no flop quando em posição (IP).',
        'sort_order': 11,
    },
    {
        'title': 'C-Bet OOP',
        'category': 'Postflop',
        'subcategory': 'C-Bet',
        'pdf_filename': 'RegLife-C-BETOOP (2).pdf',
        'description': 'Estratégia de continuation bet fora de posição (OOP).',
        'sort_order': 12,
    },
    {
        'title': 'C-Bet Turn',
        'category': 'Postflop',
        'subcategory': 'C-Bet',
        'pdf_filename': 'RegLife-C-BETTURN.pdf',
        'description': 'Continuation bet no turn: sizing, frequência e seleção de mãos.',
        'sort_order': 13,
    },
    {
        'title': 'C-Bet River',
        'category': 'Postflop',
        'subcategory': 'C-Bet',
        'pdf_filename': 'RegLife-C-BETRIVER.pdf',
        'description': 'Continuation bet no river: value bets e bluffs.',
        'sort_order': 14,
    },
    {
        'title': 'Delayed C-Bet',
        'category': 'Postflop',
        'subcategory': 'C-Bet',
        'pdf_filename': 'RegLife-DELAYEDCBET.pdf',
        'description': 'Quando e como usar delayed continuation bet.',
        'sort_order': 15,
    },
    # ── Postflop: Defesa ─────────────────────────────────────────────
    {
        'title': 'BB vs C-Bet OOP',
        'category': 'Postflop',
        'subcategory': 'Defesa',
        'pdf_filename': 'RegLife-BBvsCbet-OOP (1).pdf',
        'description': 'Estratégia do BB enfrentando c-bet fora de posição.',
        'sort_order': 16,
    },
    {
        'title': 'Enfrentando o Check-Raise',
        'category': 'Postflop',
        'subcategory': 'Defesa',
        'pdf_filename': 'RegLife-ENFRENTANDOOCHECK-RAISE.pdf',
        'description': 'Como reagir quando enfrentar check-raise no pós-flop.',
        'sort_order': 17,
    },
    {
        'title': 'Pós-Flop IP - Enfrentando C-Bet do BTN',
        'category': 'Postflop',
        'subcategory': 'Defesa',
        'pdf_filename': 'RegLife-POS-FLOPIP-enfrentandoC-betjogandodoBTN.pdf',
        'description': 'Jogando IP (do BTN) enfrentando c-bet do adversário.',
        'sort_order': 18,
    },
    # ── Postflop: Avançado ───────────────────────────────────────────
    {
        'title': 'Bet vs Missed Bet',
        'category': 'Postflop',
        'subcategory': 'Avançado',
        'pdf_filename': 'RegLife-BETVSMISSEDBET.pdf',
        'description': 'Exploração de situações quando adversário não continua apostando.',
        'sort_order': 19,
    },
    {
        'title': 'Probe do BB',
        'category': 'Postflop',
        'subcategory': 'Avançado',
        'pdf_filename': 'RegLife-PROBEDOBB.pdf',
        'description': 'Estratégia de probe bet do Big Blind no turn.',
        'sort_order': 20,
    },
    {
        'title': '3-Betted Pots Pós-Flop',
        'category': 'Postflop',
        'subcategory': 'Avançado',
        'pdf_filename': 'RegLife-3-BETTEDPOTS-POSFLOP.pdf',
        'description': 'Jogo pós-flop em potes 3-bettados: sizing e ranges.',
        'sort_order': 21,
    },
    # ── Torneios ─────────────────────────────────────────────────────
    {
        'title': 'Introdução aos Torneios Bounty',
        'category': 'Torneios',
        'subcategory': 'Bounty',
        'pdf_filename': 'RegLife-INTRODUCAOAOSTORNEIOSBOUNTY.pdf',
        'description': 'Conceitos fundamentais de torneios bounty e ajustes de range.',
        'sort_order': 22,
    },
    {
        'title': 'Torneios Bounty - Ranges Práticos',
        'category': 'Torneios',
        'subcategory': 'Bounty',
        'pdf_filename': 'RegLife-TORNEIOSBOUNTY-RANGESPRATICOS.pdf',
        'description': 'Ranges práticos para torneios bounty: call, shove e ajustes.',
        'sort_order': 23,
    },
]


def seed_lessons(conn):
    """Insert seed lessons if the lessons table is empty.

    Returns the number of lessons inserted. If lessons already exist,
    returns 0 (no-op).
    """
    row = conn.execute("SELECT COUNT(*) as cnt FROM lessons").fetchone()
    if row[0] > 0:
        return 0

    inserted = 0
    for lesson in REGLIFE_LESSONS:
        conn.execute(
            "INSERT INTO lessons (title, category, subcategory, pdf_filename, "
            "description, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
            (
                lesson['title'],
                lesson['category'],
                lesson['subcategory'],
                lesson['pdf_filename'],
                lesson['description'],
                lesson['sort_order'],
            )
        )
        inserted += 1
    conn.commit()
    return inserted
