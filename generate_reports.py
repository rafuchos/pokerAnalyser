#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script unificado para gerar relatórios de Cash Games e Torneios
"""

import sys
import io
import zipfile
from poker_cash_analyzer import PokerHandAnalyzer
from poker_tournament_analyzer import TournamentAnalyzer
from pathlib import Path

# Configura encoding para Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def extract_zip_files(folder_path):
    """Extrai todos os arquivos .zip encontrados na pasta"""
    folder = Path(folder_path)
    if not folder.exists():
        return 0

    zip_files = list(folder.glob('*.zip'))
    if not zip_files:
        return 0

    extracted_count = 0
    for zip_file in zip_files:
        try:
            print(f"   📦 Extraindo {zip_file.name}...")
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(folder)
            extracted_count += 1
        except Exception as e:
            print(f"   ⚠️  Erro ao extrair {zip_file.name}: {e}")

    return extracted_count

def main():
    print("=" * 70)
    print(" " * 20 + "POKER ANALYZER 2026")
    print("=" * 70)
    print()

    # Verifica se as pastas existem
    cash_folder = Path('data/cash')
    tournament_folder = Path('data/tournament')
    tournament_summary_folder = Path('data/tournament-summary')

    # Extrai arquivos ZIP se existirem
    print("🔍 Verificando arquivos ZIP...")
    print("-" * 70)

    cash_zips = 0
    tournament_zips = 0
    summary_zips = 0

    if cash_folder.exists():
        cash_zips = extract_zip_files(cash_folder)
        if cash_zips > 0:
            print(f"   ✅ {cash_zips} arquivo(s) ZIP extraído(s) em data/cash/")

    if tournament_folder.exists():
        tournament_zips = extract_zip_files(tournament_folder)
        if tournament_zips > 0:
            print(f"   ✅ {tournament_zips} arquivo(s) ZIP extraído(s) em data/tournament/")

    if tournament_summary_folder.exists():
        summary_zips = extract_zip_files(tournament_summary_folder)
        if summary_zips > 0:
            print(f"   ✅ {summary_zips} arquivo(s) ZIP extraído(s) em data/tournament-summary/")

    if cash_zips == 0 and tournament_zips == 0 and summary_zips == 0:
        print("   ℹ️  Nenhum arquivo ZIP encontrado.")

    print()

    reports_generated = []

    # Analisa Cash Games
    if cash_folder.exists() and list(cash_folder.glob('*.txt')):
        print("🎰 Analisando Cash Games...")
        print("-" * 70)
        cash_analyzer = PokerHandAnalyzer('data/cash')
        cash_analyzer.analyze_all_files()

        print("\n📊 Gerando relatório HTML de Cash Games...")
        cash_report = cash_analyzer.generate_html_report('cash_report.html')
        reports_generated.append(('Cash Games', cash_report))
        print()
    else:
        print("⚠️  Pasta data/cash não encontrada ou vazia. Pulando análise de cash games.")
        print()

    # Analisa Torneios
    if tournament_folder.exists() and list(tournament_folder.glob('*.txt')):
        print("⚡ Analisando Torneios...")
        print("-" * 70)
        tournament_analyzer = TournamentAnalyzer('data/tournament', pokerstars_folder='data/pokerstars')
        tournament_analyzer.analyze_all_files()

        print("\n📊 Gerando relatório HTML de Torneios...")
        tournament_report = tournament_analyzer.generate_html_report('tournament_report.html')
        reports_generated.append(('Torneios', tournament_report))
        print()
    else:
        print("⚠️  Pasta data/tournament não encontrada ou vazia. Pulando análise de torneios.")
        print()

    # Resumo final
    print("=" * 70)
    print(" " * 25 + "RESUMO FINAL")
    print("=" * 70)

    if reports_generated:
        print("\n✅ Relatórios gerados com sucesso:\n")
        for report_type, report_path in reports_generated:
            print(f"   {report_type:15} → {report_path}")
    else:
        print("\n❌ Nenhum relatório foi gerado. Verifique se existem arquivos nas pastas data/cash ou data/tournament.")

    print("\n" + "=" * 70)

if __name__ == '__main__':
    main()
