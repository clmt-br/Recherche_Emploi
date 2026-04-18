#!/usr/bin/env python3
"""
Fusion et déduplication des offres d'emploi multi-sources.

Charge les rapports JSON de chaque source (LinkedIn, APEC, WTTJ, et toute
future source), déduplique par couple (titre, entreprise) normalisé, et
produit un JSON unique avec les meilleures entrées.

Pour ajouter une nouvelle plateforme :
  1. Créer le script <plateforme>_batch.py qui produit un JSON
  2. Ajouter une entrée dans SOURCE_FILES (ou utiliser --inputs)
  3. S'assurer que chaque offre du JSON a au minimum :
     job_id, title, company, url, score, verdict, reasons

Usage:
    python merge_sources.py                           # Sources par défaut
    python merge_sources.py --inputs a.json b.json    # Sources manuelles
    python merge_sources.py --output merged.json      # Fichier de sortie
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Sources connues — ajouter ici toute nouvelle plateforme
# ---------------------------------------------------------------------------

SOURCE_FILES = {
    "LinkedIn": SCRIPT_DIR / "linkedin_dernier_rapport.json",
    "APEC":     SCRIPT_DIR / "apec_dernier_rapport.json",
    "WTTJ":     SCRIPT_DIR / "wttj_dernier_rapport.json",
    # "Indeed":  SCRIPT_DIR / "indeed_dernier_rapport.json",
    # "Hellowork": SCRIPT_DIR / "hellowork_dernier_rapport.json",
}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# Mots à supprimer pour la comparaison (bruit dans les titres)
STOP_WORDS = {
    "h/f", "f/h", "h-f", "f-h", "m/f", "f/m",
    "cdi", "cdd", "stage", "alternance", "interim",
    "ingénieur", "ingenieur", "ingénieure", "ingenieure",
    "chargé", "charge", "chargée", "chargee",
    "responsable", "manager", "lead", "senior", "junior",
    "confirmé", "confirme", "expérimenté", "experimente",
    "poste", "emploi", "offre",
    "de", "du", "des", "le", "la", "les", "l", "d", "en", "et", "ou",
    "à", "a", "au", "aux",
}


def normalize(text: str) -> str:
    """Normalise un texte pour comparaison : minuscule, sans accents,
    sans ponctuation, sans stop words."""
    if not text:
        return ""
    # Minuscule
    text = text.lower()
    # Supprimer les accents
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Remplacer ponctuation par des espaces
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Supprimer les stop words
    words = [w for w in text.split() if w not in STOP_WORDS and len(w) > 1]
    # Trier pour être insensible à l'ordre
    words.sort()
    return " ".join(words)


def make_key(job: dict) -> str:
    """Génère une clé de déduplication à partir du titre et de l'entreprise."""
    title_norm = normalize(job.get("title") or "")
    company_norm = normalize(job.get("company") or "")
    return f"{company_norm}||{title_norm}"


# ---------------------------------------------------------------------------
# Score de richesse (pour choisir la meilleure source)
# ---------------------------------------------------------------------------

# Champs qui comptent pour déterminer quelle entrée est la plus riche
RICHNESS_FIELDS = [
    "description", "salary", "experience_level", "experience_min",
    "listed_date", "location", "contract", "company",
    "sectors", "industries", "remote", "company_description",
]


def richness_score(job: dict) -> int:
    """Score = nombre de champs non vides. Plus c'est riche, mieux c'est."""
    score = 0
    for field in RICHNESS_FIELDS:
        val = job.get(field)
        if val is not None and val != "" and val != [] and val != {}:
            score += 1
    # Bonus pour description longue (plus d'infos)
    desc = job.get("description") or ""
    if len(desc) > 500:
        score += 2
    elif len(desc) > 200:
        score += 1
    return score


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------

def load_source(filepath: Path, source_name: str) -> list[dict]:
    """Charge un fichier JSON et tague chaque offre avec sa source."""
    if not filepath.exists():
        print(f"  [{source_name}] Fichier absent: {filepath} — ignoré", file=sys.stderr)
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [{source_name}] Erreur lecture: {e} — ignoré", file=sys.stderr)
        return []

    if not isinstance(jobs, list):
        print(f"  [{source_name}] Format inattendu (pas une liste) — ignoré", file=sys.stderr)
        return []

    # S'assurer que chaque offre a un champ source
    for job in jobs:
        if not job.get("source"):
            job["source"] = source_name

    print(f"  [{source_name}] {len(jobs)} offres chargées", file=sys.stderr)
    return jobs


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------

def merge_jobs(all_jobs: list[dict]) -> list[dict]:
    """Déduplique les offres par (titre, entreprise) normalisé.
    Garde l'entrée la plus riche. Stocke les sources alternatives."""

    groups: dict[str, list[dict]] = {}

    for job in all_jobs:
        key = make_key(job)
        if key not in groups:
            groups[key] = []
        groups[key].append(job)

    merged = []
    duplicates_count = 0

    for key, candidates in groups.items():
        if len(candidates) == 1:
            best = candidates[0]
        else:
            # Trier par richesse décroissante, puis par score décroissant
            candidates.sort(key=lambda j: (richness_score(j), j.get("score", 0)), reverse=True)
            best = candidates[0]
            duplicates_count += len(candidates) - 1

            # Noter les sources alternatives
            alt_sources = [j.get("source", "?") for j in candidates[1:]]
            best["also_on"] = alt_sources

        merged.append(best)

    print(f"\n  Fusion: {len(all_jobs)} → {len(merged)} offres uniques ({duplicates_count} doublons supprimés)", file=sys.stderr)
    return merged


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def generate_report(jobs: list[dict]) -> str:
    jobs_sorted = sorted(jobs, key=lambda j: j.get("score", 0), reverse=True)

    a_postuler = [j for j in jobs_sorted if j.get("verdict") == "A_POSTULER"]
    a_examiner = [j for j in jobs_sorted if j.get("verdict") == "A_EXAMINER"]
    eliminees = [j for j in jobs_sorted if j.get("verdict") == "ELIMINEE"]

    lines = [
        f"# Rapport fusionné — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"**{len(jobs_sorted)} offres uniques** (après déduplication inter-sources)",
        f"- A postuler : {len(a_postuler)}",
        f"- A examiner : {len(a_examiner)}",
        f"- Éliminées  : {len(eliminees)}",
        "",
        "| Score | Verdict | Intitulé | Entreprise | Source | Aussi sur | Raisons | Lien |",
        "|-------|---------|----------|------------|--------|-----------|---------|------|",
    ]

    for j in jobs_sorted:
        verdict_label = {
            "A_POSTULER": "A postuler",
            "A_EXAMINER": "A examiner",
            "ELIMINEE": "Eliminée",
        }.get(j.get("verdict", ""), "?")

        title = (j.get("title") or "?")[:45]
        company = (j.get("company") or "?")[:20]
        source = j.get("source", "?")
        also_on = ", ".join(j.get("also_on", []))
        reasons = "; ".join(j.get("reasons", []))[:50]
        url = j.get("url", "")

        lines.append(
            f"| {j.get('score', 0):3d} | {verdict_label} | {title} | {company} | {source} | {also_on} | {reasons} | [Lien]({url}) |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fusionne et déduplique les offres de toutes les sources"
    )
    parser.add_argument(
        "--inputs", nargs="+",
        help="Fichiers JSON à fusionner (par défaut : sources connues dans SOURCE_FILES)"
    )
    parser.add_argument(
        "--output", "-o", type=str,
        default=str(SCRIPT_DIR / "merged_rapport.json"),
        help="Fichier de sortie JSON fusionné"
    )
    parser.add_argument(
        "--report", "-r", type=str,
        help="Fichier de sortie rapport markdown"
    )

    args = parser.parse_args()

    # Chargement
    all_jobs = []
    print("Chargement des sources...", file=sys.stderr)

    if args.inputs:
        # Mode manuel : fichiers passés en argument
        for filepath in args.inputs:
            p = Path(filepath)
            source_name = p.stem.replace("_dernier_rapport", "").replace("_", " ").title()
            all_jobs.extend(load_source(p, source_name))
    else:
        # Mode auto : sources connues
        for source_name, filepath in SOURCE_FILES.items():
            all_jobs.extend(load_source(filepath, source_name))

    if not all_jobs:
        print("Aucune offre chargée.", file=sys.stderr)
        return

    # Fusion
    merged = merge_jobs(all_jobs)

    # Tri par score décroissant
    merged.sort(key=lambda j: j.get("score", 0), reverse=True)

    # Affichage résumé
    for j in merged:
        v = j.get("verdict", "?")
        s = j.get("score", 0)
        t = (j.get("title") or "?")[:45]
        c = (j.get("company") or "?")[:20]
        src = j.get("source", "?")
        also = f" +{','.join(j['also_on'])}" if j.get("also_on") else ""
        print(f"  {v:12s} ({s:3d}) | {t} | {c} | {src}{also}", file=sys.stderr)

    # Rapport markdown
    report = generate_report(merged)
    print(report)

    # Sauvegarde JSON
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"\nJSON fusionné: {args.output}", file=sys.stderr)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Rapport: {args.report}", file=sys.stderr)

    # Stats finales
    sources_count = {}
    for j in merged:
        src = j.get("source", "?")
        sources_count[src] = sources_count.get(src, 0) + 1
    print("\nRépartition par source:", file=sys.stderr)
    for src, count in sorted(sources_count.items()):
        print(f"  {src}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
