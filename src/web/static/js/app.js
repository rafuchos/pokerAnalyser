/* Poker Analyzer Web UI – client-side helpers */

/* ── Stat Tooltips Dictionary ─────────────────────────────────────── */
var STAT_TOOLTIPS = {
    // Preflop
    'VPIP':          'Voluntarily Put $ In Pot — % de vezes que você colocou dinheiro no pot voluntariamente (call ou raise preflop). Não inclui blinds obrigatórios.',
    'PFR':           'Pre-Flop Raise — % de vezes que você fez raise preflop. Um PFR alto indica jogo agressivo.',
    '3Bet':          '3-Bet — % de vezes que você fez re-raise (3bet) preflop quando teve oportunidade.',
    '3-Bet':         '3-Bet — % de vezes que você fez re-raise (3bet) preflop quando teve oportunidade.',
    '3-Bet%':        '3-Bet — % de vezes que você fez re-raise (3bet) preflop quando teve oportunidade.',
    'F3B':           'Fold to 3-Bet — % de vezes que você foldou quando levou 3bet. Alto demais = preflop leaky.',
    'Fold to 3-Bet': 'Fold to 3-Bet — % de vezes que você foldou quando levou 3bet.',
    'ATS':           'Attempt to Steal — % de vezes que você tentou roubar os blinds (raise do CO, BTN ou SB).',
    'OShv':          'Open Shove — % de vezes que você fez all-in como primeiro raise (open shove). Mais relevante em torneios short stack.',
    'RBW':           'Raise by Walk — % de vezes que você deu raise quando recebeu walk no BB (todos foldaram até você).',
    'Fold to Steal%':'Fold to Steal — % de vezes que você foldou nos blinds quando enfrentou tentativa de steal.',
    '3-Bet vs Steal%':'3-Bet vs Steal — % de vezes que você fez 3bet contra tentativa de steal.',
    'Call vs Steal%': 'Call vs Steal — % de vezes que você fez call contra tentativa de steal.',

    // Postflop
    'AF':            'Aggression Factor — Razão (bets+raises)/calls no postflop. AF > 2 indica jogo agressivo.',
    'AFq':           'Aggression Frequency — % de ações agressivas (bet/raise) vs total de ações no postflop.',
    'CBet':          'Continuation Bet — % de vezes que você fez cbet no flop como aggressor preflop.',
    'FCB':           'Fold to CBet — % de vezes que você foldou quando enfrentou continuation bet.',
    'Fold to CBet':  'Fold to CBet — % de vezes que você foldou quando enfrentou continuation bet.',
    'WTSD':          'Went to Showdown — % de vezes que você foi ao showdown quando viu o flop. Indica quão sticky você é.',
    'W$SD':          'Won $ at Showdown — % de vezes que você ganhou dinheiro quando foi ao showdown. Indica qualidade das mãos que você leva ao showdown.',
    'WFlop':         'Won Saw Flop — % de vitórias entre mãos que viram o flop (inclui wins sem showdown).',
    'BRvr':          'Bet River — % de vezes que você apostou no river quando teve oportunidade.',
    'CRvr':          'Call River — % de vezes que você pagou aposta no river.',
    'Probe':         'Probe Bet — % de vezes que você apostou quando o aggressor preflop não fez cbet.',
    'FProbe':        'Fold to Probe — % de vezes que você foldou quando levou probe bet.',
    'BMCB':          'Bet vs Missed CBet — % de vezes que você apostou quando o aggressor não fez continuation bet.',
    'XF':            'Check-Fold OOP — % de vezes que você fez check-fold quando estava fora de posição.',
    'Check-Raise':   'Check-Raise — % de vezes que você fez check-raise no postflop.',
    'Check-Raise%':  'Check-Raise — % de vezes que você fez check-raise no postflop.',

    // Financial / Win Rate
    'bb/100':        'Big Blinds per 100 hands — Win rate normalizado. Positivo = ganhando, negativo = perdendo.',
    'Real bb/100':   'Win rate real em bb/100 — Resultado efetivo incluindo variância.',
    'EV bb/100':     'Expected Value bb/100 — Win rate esperado baseado nas decisões, removendo a variância dos all-ins.',
    'Net Profit':    'Lucro líquido total no período.',
    'Net (BB)':      'Resultado líquido em Big Blinds.',
    'Luck Factor':   'Diferença entre resultado real e EV esperado. Positivo = running hot, negativo = running cold.',
    'Difference (Luck)': 'Diferença entre Real bb/100 e EV bb/100. Mede quanto a sorte impactou o resultado.',
    'Running Luck':  'Soma acumulada de (Real - EV). Mostra se você está running acima ou abaixo do esperado.',
    '$/hr':          'Dólares por hora — Win rate baseado no tempo de jogo.',
    'Win Rate':      'Taxa de vitória geral.',
    'Avg Profit':    'Lucro médio por sessão ou período.',
    'Real Net':      'Resultado real (dinheiro efetivamente ganho/perdido).',
    'EV Net':        'Resultado esperado (baseado em equity nos all-ins).',
    'Luck':          'Diferença entre resultado real e esperado (Real - EV).',
    'ROI':           'Return on Investment — (Prize - Buy-in) / Buy-in × 100%. Mede retorno sobre investimento em torneios.',
    'ITM':           'In The Money — % de vezes que você terminou nas posições pagas.',

    // EV & Variance
    'All-In Hands':  'Número de mãos que foram a all-in com showdown. Usadas para calcular EV ajustado.',
    'All-Ins':       'Número de situações de all-in na sessão.',

    // Session / Time
    'Total Hands':   'Número total de mãos jogadas no período.',
    'Hands':         'Número de mãos jogadas.',
    'Sessions':      'Número de sessões de jogo no período.',
    'Duration':      'Tempo total de jogo.',
    'Days Played':   'Número de dias em que você jogou.',

    // Health / Quality
    'Health Score':  'Pontuação de saúde do jogo (0-100) baseada em quão próximos seus stats estão dos ranges ideais.',
    'Grade':         'Nota geral do jogo (A+ a F) baseada no Health Score e nos leaks detectados.',
    'Cost (BB)':     'Custo estimado do leak em Big Blinds.',
    'Cost bb/100':   'Custo estimado do leak em bb/100. Quanto esse leak está custando a cada 100 mãos.',

    // Sizing
    'Pot Type':      'Classificação do tamanho do pot (small, medium, large).',
    'Avg Pot':       'Tamanho médio do pot nessa categoria.',

    // Tilt
    'Tilt Sessions': 'Número de sessões onde sinais de tilt foram detectados.',
    'Tilt Rate':     'Percentual de sessões com indicadores de tilt.',
    'Tilt Cost':     'Estimativa de quanto o tilt custou em Big Blinds.',
    'Recovery Rate':  'Percentual de vezes que você se recuperou após um bad beat.',
    'Bad Beats':     'Número de situações onde você perdeu tendo a melhor mão (equity > 60%).',
    'Stop-Loss':     'Sugestão de limite de perda por sessão para evitar tilt.',

    // Leak
    'Severity':      'Gravidade do leak: high = impacto grande no win rate, medium = moderado, low = pequeno.',

    // Range
    'Dealt':         'Número de vezes que você recebeu essa combinação de cartas.',
    'Played':        'Número de vezes que você jogou (VPIP) essa combinação.',
    'Freq%':         'Frequência de jogo — % de vezes que você jogou essa mão quando recebeu.',

    // Decision Tree
    'Total Net':     'Resultado líquido total para essa decisão.',
    'Avg Net':       'Resultado médio por vez que essa decisão foi tomada.',
    'Count':         'Número de vezes que essa situação ocorreu.',

    // Tournament specific
    'Buy-in':        'Custo de entrada do torneio.',
    'Prize':         'Premiação recebida.',
    'Position':      'Posição final no torneio.',
    'Entries':       'Número total de entradas no torneio.',
    'Win Rate %':    'Percentual de vitórias (prize > 0).',
};

function applyStatTooltips() {
    // Apply to stat-label divs
    document.querySelectorAll('.stat-label').forEach(function (el) {
        var text = el.textContent.trim();
        if (STAT_TOOLTIPS[text]) {
            el.title = STAT_TOOLTIPS[text];
            el.style.cursor = 'help';
        }
    });

    // Apply to table headers (skip hud-table to avoid layout issues)
    document.querySelectorAll('th').forEach(function (el) {
        if (el.closest('.hud-table')) return;
        var text = el.textContent.trim();
        if (STAT_TOOLTIPS[text]) {
            el.title = STAT_TOOLTIPS[text];
            el.style.cursor = 'help';
        }
    });

    // Apply to card-title divs that match stat names
    document.querySelectorAll('.card-title').forEach(function (el) {
        var text = el.textContent.trim();
        if (STAT_TOOLTIPS[text]) {
            el.title = STAT_TOOLTIPS[text];
            el.style.cursor = 'help';
        }
    });

    // Apply to HUD stat labels (leak-name, sdc-chart-label, etc.)
    document.querySelectorAll('.leak-name, .sdc-chart-label, .comparison-label, .notable-label, .filter-label').forEach(function (el) {
        var text = el.textContent.trim();
        if (STAT_TOOLTIPS[text]) {
            el.title = STAT_TOOLTIPS[text];
            el.style.cursor = 'help';
        }
    });

    // Apply to any element with data-stat attribute
    document.querySelectorAll('[data-stat]').forEach(function (el) {
        var stat = el.dataset.stat;
        if (STAT_TOOLTIPS[stat]) {
            el.title = STAT_TOOLTIPS[stat];
            el.style.cursor = 'help';
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    // Highlight active sub-nav on scroll (future use)
    // Currently tabs are server-rendered via Jinja2

    // Accordion toggles (for session cards, if present)
    document.querySelectorAll('[data-toggle="accordion"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var target = document.getElementById(btn.dataset.target);
            if (target) {
                target.classList.toggle('collapsed');
                btn.classList.toggle('expanded');
            }
        });
    });

    // Apply stat tooltips
    applyStatTooltips();
});
