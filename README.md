# Poker Analyzer - Sistema de Análise de Mãos 🎰⚡

Sistema completo para analisar históricos de mãos de poker, tanto Cash Games quanto Torneios, gerando relatórios HTML detalhados por dia.

## 📁 Estrutura de Pastas

```
CashHandTracking/
├── data/
│   ├── cash/           # Arquivos .txt de cash games
│   └── tournament/     # Arquivos .txt de torneios
├── poker_cash_analyzer.py        # Analisador de Cash Games
├── poker_tournament_analyzer.py  # Analisador de Torneios
├── generate_reports.py            # Script unificado
└── README.md
```

## 🎯 Como Usar

### Opção 1: Gerar Ambos os Relatórios (Recomendado)

```bash
python generate_reports.py
```

**Recursos automáticos:**
- 📦 Extrai automaticamente arquivos .zip nas pastas data/cash e data/tournament
- 🎰 Analisa cash games
- ⚡ Analisa torneios
- 📊 Gera relatórios HTML

**Gera automaticamente:**
- `cash_report.html` - Relatório de Cash Games
- `tournament_report.html` - Relatório de Torneios

### Opção 2: Gerar Apenas Cash Games

```bash
python poker_cash_analyzer.py
```

Gera: `poker_report.html`

### Opção 3: Gerar Apenas Torneios

```bash
python poker_tournament_analyzer.py
```

Gera: `tournament_report.html`

## 📊 Análise de Cash Games

### O que é analisado:
- **Sessões automáticas**: Detecta início/fim de sessões baseado em bust ou mudança de dia
- **Estatísticas por dia**:
  - Total de mãos jogadas
  - Número de sessões
  - Total investido (buy-ins reais, sem contar reload)
  - Resultado final (lucro/prejuízo)
  - Mãos notáveis (maior ganho e maior perda do dia)
- **Resumo geral**:
  - Total de mãos
  - Dias jogados
  - Dias positivos vs negativos
  - Resultado total
  - Média por dia

### Como funciona a detecção de sessões:
1. Nova sessão começa quando:
   - É a primeira mão do dia
   - O stack anterior chegou a $0 (bust)
   - Mudou de dia

2. Buy-in real é calculado:
   - Primeira sessão do dia: valor completo
   - Sessão após bust: valor completo
   - Sessão sem bust anterior: apenas a diferença (se > $5)

## ⚡ Análise de Torneios

### O que é analisado:
- **Extração automática de Buy-in**: Identifica o valor do buy-in do nome do torneio
- **Identificação de Rebuys**: Detecta quando você deu rebuy (stack zerou e depois reapareceu no mesmo torneio)
- **Cálculo de Prêmios**: Extrai informações de colocação e prêmio do histórico
- **Estatísticas por dia**:
  - Quantidade de torneios únicos
  - **Total investido em $** (buy-ins + rebuys)
  - **Total ganho em $** (soma de todos os prêmios)
  - **Resultado final em $** (ganho - investido)
  - Número de entries (buy-in inicial + rebuys)
  - Detalhes de cada torneio:
    - Nome do torneio
    - Status com posição (🥇 Campeão, 🥈 Vice, 🥉 3º, 🏆 Xº lugar, ou 💀 Busted)
    - **Buy-in unitário e total investido**
    - **Prêmio ganho**
    - **Lucro/Prejuízo do torneio**
    - Número de entries (1 + rebuys)
    - Mãos jogadas
    - Max stack alcançado
    - Stack final
    - Horário
- **Resumo geral**:
  - Total de torneios
  - **Total investido ($)**
  - **Total ganho ($)**
  - **Resultado final ($)**
  - Total de entries
  - Total de rebuys
  - Dias jogados
  - **Média de buy-in por dia**
  - Média de torneios/dia

### Como funciona:
1. **Extração de Buy-in**:
   - Identifica valores no nome do torneio ("15 Bounty Hunters", "Mini Main 5.40", etc.)
   - Detecta freerolls automaticamente
   - Para Spin & Gold, usa valor padrão de $2

2. **Detecção de Rebuys**:
   - Agrupa todas as mãos por Tournament ID
   - Analisa a sequência de stacks: Se stack anterior = 0 e stack atual > 1000 → Rebuy detectado
   - Conta entries = 1 (buy-in inicial) + rebuys

3. **Extração de Prêmios**:
   - Busca por linhas como "Hero finished in 5th place and received $12.34"
   - Calcula lucro = prêmio - (buy-in × entries)

## 🎨 Relatórios HTML

### Cash Games (Verde)
- Tema escuro com acentos verdes (#00ff88)
- Organizado por dia (mais recente primeiro)
- Mostra sessões detalhadas
- Destaca mãos notáveis (maior ganho/perda)

### Torneios (Laranja)
- Tema escuro com acentos laranjas (#ff8800)
- Organizado por dia (mais recente primeiro)
- Lista todos os torneios do dia
- Código de cores: Verde = Sobreviveu, Vermelho = Busted

## 📝 Formato dos Arquivos

Os arquivos devem estar no formato de histórico de mãos do GGPoker:

### Cash Games
```
Poker Hand #HD123456: Hold'em No Limit ($0.25/$0.50) - 2026/01/10 12:00:00
Table 'Rush123' 6-max Seat #1 is the button
...
```

### Torneios
```
Poker Hand #TM123456: Tournament #789, Nome do Torneio Hold'em No Limit - Level1(10/20) - 2026/01/10 12:00:00
...
```

## 🔧 Requisitos

- Python 3.6+
- Bibliotecas padrão (re, datetime, pathlib, collections)

## 💡 Dicas

1. **Organize seus arquivos**:
   - Coloque arquivos .zip ou .txt de cash em `data/cash/`
   - Coloque arquivos .zip ou .txt de torneios em `data/tournament/`
   - O script `generate_reports.py` extrai automaticamente os .zip

2. **Arquivos ZIP**:
   - ✅ **AUTOMÁTICO**: Use `python generate_reports.py` - ele extrai tudo sozinho!
   - ⚙️ **Manual** (se preferir):
     ```bash
     cd data/cash
     unzip *.zip
     ```

3. **Filtragem por ano**: Os relatórios filtram automaticamente apenas dados de 2026 (pode ser ajustado no código)

4. **Visualização**: Abra os arquivos .html em qualquer navegador para ver os relatórios

5. **Primeira vez**: Basta colocar os .zip nas pastas e rodar `python generate_reports.py` - tudo é automático!

## 📈 Futuras Melhorias

- [ ] Extração automática de buy-in do nome do torneio
- [ ] Cálculo de ROI em torneios
- [ ] Gráficos de evolução temporal
- [ ] Estatísticas de posição e ranges
- [ ] Análise de All-in EV

## 📄 Licença

Projeto pessoal para análise de poker.
