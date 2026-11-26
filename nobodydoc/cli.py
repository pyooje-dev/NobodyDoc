"""Ligne de commande (utile pour les tests ; l'interface graphique viendra ensuite).

    python -m nobodydoc fichier1.docx fichier2.xlsx --sortie dossier --dictionnaire dico.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .detectors.rules import ALL_RULE_CATEGORIES
from .dictionary import CompanyDictionary
from .pipeline import anonymize_files, restore_files
from .session import AnonymizationSession, SessionConfig
from .vault import TableStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nobodydoc", description="Anonymise des documents en local.")
    parser.add_argument("fichiers", nargs="+", type=Path)
    parser.add_argument("--sortie", type=Path, default=Path("sortie_anonymisee"))
    parser.add_argument("--dictionnaire", type=Path, help="Termes de l'entreprise (.json ou .csv)")
    parser.add_argument("--sans-ner", action="store_true", help="Désactive la détection des noms par le modèle")
    parser.add_argument("--lieux", action="store_true", help="Masque aussi les villes et pays détectés")
    parser.add_argument("--table", action="store_true", help="Affiche la table de correspondance")
    parser.add_argument("--sans-sauvegarde", action="store_true",
                        help="N'enregistre pas la table chiffrée (restauration impossible ensuite)")
    parser.add_argument("--restaurer", metavar="TABLE", nargs="?", const="derniere",
                        help="Remet les vraies valeurs dans les fichiers donnés. TABLE : chemin d'une "
                             "table .ndtable (par défaut, la plus récente)")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.restaurer:
        return _restore(args)

    dictionary = CompanyDictionary.load(args.dictionnaire) if args.dictionnaire else None
    config = SessionConfig(
        rule_categories=ALL_RULE_CATEGORIES,
        use_ner=not args.sans_ner,
        ner_labels=("PER", "ORG", "LOC") if args.lieux else ("PER", "ORG"),
    )
    session = AnonymizationSession(config, dictionary)
    if session.ner is not None and not session.ner.available:
        print("Attention : modèle de langue introuvable, les noms ne seront détectés que par le dictionnaire.")

    files = [p for p in args.fichiers if p.is_file()]
    reports = anonymize_files(files, session, args.sortie)
    exit_code = 0
    for report in reports:
        name = Path(report.source).name
        if report.error:
            print(f"✗ {name} : {report.error}")
            exit_code = 1
            continue
        detail = ", ".join(f"{cat} {n}" for cat, n in sorted(report.replacements.items()))
        print(f"✓ {name} -> {report.output}  ({report.total} remplacements{' : ' + detail if detail else ''})")
        for warning in report.warnings:
            print(f"    ! {warning}")
    if not args.sans_sauvegarde and any(not r.error for r in reports):
        path = TableStore().save_session(session, [r.source for r in reports if not r.error])
        print(f"\nTable de correspondance chiffrée enregistrée : {path}")
    if args.table:
        print("\nTable de correspondance :")
        for entity in session.entity_list():
            print(f"  {entity.placeholder:<22} {' | '.join(sorted(entity.values))}")
    return exit_code


def _restore(args) -> int:
    store = TableStore()
    if args.restaurer == "derniere":
        tables = store.list()
        if not tables:
            print("Aucune table de correspondance enregistrée sur ce poste.")
            return 1
        table = tables[0]
    else:
        table = store.load(Path(args.restaurer))
    print(f"Table utilisée : {table.label}")
    files = [p for p in args.fichiers if p.is_file()]
    exit_code = 0
    for report in restore_files(files, table):
        name = Path(report.source).name
        if report.error:
            print(f"✗ {name} : {report.error}")
            exit_code = 1
            continue
        print(f"✓ {name} -> {report.output}  ({report.total} valeurs restaurées)")
        for warning in report.warnings:
            print(f"    ! {warning}")
    return exit_code
