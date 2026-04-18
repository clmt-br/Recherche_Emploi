#!/usr/bin/env python3
"""
WTTJ (Welcome to the Jungle) Batch Search & Classifier
Recherche des offres WTTJ via Algolia, les analyse et les classe
selon les criteres du profil candidat.

Aucune authentification requise - WTTJ utilise Algolia avec cles publiques.

Usage:
    python wttj_batch.py                                  # Recherches par defaut (profil Clement)
    python wttj_batch.py --queries "ingenieur mecanique" "technico-commercial"
    python wttj_batch.py --max 20 --output rapport.json
"""

import argparse
import json
import os
import re
import sys
import time
import random
from datetime import datetime
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Constantes Algolia WTTJ
# ---------------------------------------------------------------------------

ALGOLIA_APP_ID = "CSEKHVMS53"
ALGOLIA_API_KEY = "4bd8f6215d0cc52b26430765769e65a0"
ALGOLIA_INDEX = "wttj_jobs_production_fr"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"

ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "Content-Type": "application/json",
    "Referer": "https://www.welcometothejungle.com/",
    "Origin": "https://www.welcometothejungle.com",
}

# Centre IDF (Paris) et rayon 50km
IDF_LAT = 48.8566
IDF_LNG = 2.3522
IDF_RADIUS = 50000  # metres

# Recherches par defaut
DEFAULT_QUERIES = [
    "ingénieur bureau d'études mécanique",
    "ingénieur mécatronique",
    "ingénieur méthodes industrialisation",
    "ingénieur conception mécanique",
    "chargé d'études mécaniques",
    "technico-commercial ingénieur",
    "ingénieur qualité normalisation",
    "chef de projet technique junior",
    "ingénieur automatisme GTB",
    "ingénieur automaticien CVC",
    "ingénieur supervision bâtiment",
]

CONTRACT_MAP = {
    "full_time": "CDI",
    "fixed_term": "CDD",
    "internship": "Stage",
    "apprenticeship": "Alternance",
    "temporary": "Intérim",
    "freelance": "Freelance",
    "vie": "VIE",
    "other": "Autre",
}

# ---------------------------------------------------------------------------
# Classification (memes listes que linkedin_batch.py / apec_batch.py)
# ---------------------------------------------------------------------------

PRESTA_KEYWORDS = [
    "consulting", "conseil en ingénierie", "assistance technique",
    "société de conseil", "esn", "ssii", "prestataire", "ingénierie externalisée",
    "délégation", "régie", "mise à disposition",
]

PRESTA_COMPANIES = [
    "alten", "altran", "akka", "assystem", "segula", "expleo", "sopra",
    "capgemini", "atos", "cgi", "modis", "systra", "ausy", "astek",
    "davidson", "aubay", "talan", "devoteam", "onepoint", "sii",
    "parlym", "orinox", "ameg", "kicklox", "freelance",
    "ametra", "migso", "pcubed", "apside", "squadra", "accenture",
    "bertrandt", "adecco", "randstad", "manpower", "michael page",
    "hays", "expectra", "spring", "page personnel",
    "ardian", "betamint", "extia", "inexia", "inetum",
    "wavestone", "twelve", "mc2i", "scalian", "enser",
    "ingeliance", "elsys", "supplay", "apave", "socotec",
]

ARMEMENT_KEYWORDS = [
    "armement", "défense militaire", "missile", "munition",
    "arme", "balistique", "pyrotechnie",
]

CORE_SKILLS = [
    "mécanique", "conception", "cao", "catia", "solidworks",
    "cotation", "gps", "iso", "dessin technique", "mise en plan",
    "gestion de projet", "bureau d'études", "méthodes",
    "industrialisation", "qualité", "normalisation",
    "technico-commercial", "avant-vente", "ingénieur commercial",
    "mécatronique", "robotique", "python", "automatisme",
]

OUT_OF_SCOPE = [
    "génie civil", "btp", "bâtiment", "charpente",
    "génie électrique pur", "haute tension", "transformateur",
    "sûreté physique", "incendie",
    "développeur", "data scientist", "devops",
    "infirmier", "médecin", "pharmacien",
    "comptable", "juriste", "avocat",
    "trade marketing", "community manager",
]


# ---------------------------------------------------------------------------
# Recherche WTTJ (Algolia)
# ---------------------------------------------------------------------------

def search_jobs(query: str, count: int = 20) -> list[dict]:
    """Recherche WTTJ via Algolia et retourne la liste des offres."""
    all_results = []
    page = 0
    hits_per_page = min(count, 20)

    while len(all_results) < count:
        payload = {
            "query": query,
            "hitsPerPage": hits_per_page,
            "page": page,
            "aroundLatLng": f"{IDF_LAT},{IDF_LNG}",
            "aroundRadius": IDF_RADIUS,
            "facetFilters": [["contract_type:full_time"]],
        }

        time.sleep(random.uniform(0.3, 0.8))
        try:
            resp = requests.post(ALGOLIA_URL, json=payload, headers=ALGOLIA_HEADERS, timeout=15)
        except requests.RequestException as e:
            print(f"  Erreur reseau: {e}", file=sys.stderr)
            break

        if resp.status_code != 200:
            print(f"  Erreur HTTP {resp.status_code} pour '{query}'", file=sys.stderr)
            break

        data = resp.json()
        hits = data.get("hits", [])
        total_pages = data.get("nbPages", 0)

        if not hits:
            break

        all_results.extend(hits)
        page += 1

        if page >= total_pages or len(all_results) >= count:
            break

    return all_results[:count]


def parse_offre(raw: dict) -> dict:
    """Convertit une offre WTTJ brute en format standardise."""
    job_id = raw.get("reference") or raw.get("objectID") or ""

    # Organisation
    org = raw.get("organization") or {}
    company = org.get("name", "")
    org_slug = org.get("slug", "")

    # Slug pour URL
    slug = raw.get("slug", "")
    url = f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{slug}" if org_slug and slug else ""

    # Localisation
    offices = raw.get("offices") or []
    if offices:
        loc_parts = []
        office = offices[0]
        if office.get("city"):
            loc_parts.append(office["city"])
        if office.get("state"):
            loc_parts.append(office["state"])
        location = ", ".join(loc_parts)
    else:
        location = ""

    # Contrat
    contract_raw = raw.get("contract_type", "")
    contract = CONTRACT_MAP.get(contract_raw, contract_raw)

    # Salaire
    sal_min = raw.get("salary_minimum")
    sal_max = raw.get("salary_maximum")
    sal_currency = raw.get("salary_currency", "")
    sal_period = raw.get("salary_period", "")
    if sal_min and sal_max:
        salary = f"{sal_min} - {sal_max} {sal_currency} ({sal_period})"
    elif sal_min:
        salary = f"A partir de {sal_min} {sal_currency}"
    else:
        salary = ""

    # Description = summary + missions
    summary = raw.get("summary") or ""
    missions = raw.get("key_missions") or []
    if isinstance(missions, list):
        missions_text = " ".join(missions)
    else:
        missions_text = str(missions)
    description = f"{summary} {missions_text}".strip()

    # Experience
    exp_min = raw.get("experience_level_minimum")

    # Date publication
    published = (raw.get("published_at") or "")[:10]

    # Remote
    remote = raw.get("remote", "no")

    return {
        "job_id": str(job_id),
        "source": "WTTJ",
        "url": url,
        "title": raw.get("name", ""),
        "company": company,
        "location": location,
        "salary": salary,
        "contract": contract,
        "description": description,
        "listed_date": published,
        "experience_min": exp_min,
        "remote": remote,
        "sectors": [s.get("name", "") for s in (raw.get("sectors") or [])],
    }


# ---------------------------------------------------------------------------
# Classificateur
# ---------------------------------------------------------------------------

def classify_job(job: dict) -> dict:
    """Classe une offre selon les criteres du profil candidat."""
    title = (job.get("title") or "").lower()
    company = (job.get("company") or "").lower()
    desc = (job.get("description") or "").lower()
    salary = (job.get("salary") or "").lower()
    location = (job.get("location") or "").lower()
    all_text = f"{title} {desc}"

    reasons = []
    score = 50

    # --- Eliminatoires ---

    # Presta / ESN
    is_presta = False
    if any(kw in company for kw in PRESTA_COMPANIES):
        is_presta = True
        reasons.append(f"Presta/ESN ({job.get('company')})")
    if any(kw in all_text for kw in PRESTA_KEYWORDS):
        is_presta = True
        if "Presta" not in " ".join(reasons):
            reasons.append("Indicateurs presta dans description")
    if is_presta:
        score -= 40

    # Armement
    if any(kw in all_text for kw in ARMEMENT_KEYWORDS):
        reasons.append("Secteur armement")
        score -= 50

    # Hors profil
    if any(kw in all_text for kw in OUT_OF_SCOPE):
        matched = [kw for kw in OUT_OF_SCOPE if kw in all_text]
        reasons.append(f"Hors profil ({', '.join(matched[:2])})")
        score -= 30

    # Experience minimum (champ Algolia)
    exp_min = job.get("experience_min")
    if exp_min is not None:
        try:
            exp_val = float(exp_min)
            if exp_val >= 5:
                reasons.append(f"{exp_val:.0f} ans d'exp. requis (champ WTTJ)")
                score -= 30
            elif exp_val >= 3:
                reasons.append(f"{exp_val:.0f} ans d'exp. requis (limite)")
                score -= 10
        except (ValueError, TypeError):
            pass

    # Experience dans la description (regex)
    desc_exp = re.findall(r"(\d+)\s*(?:ans?|années?)\s*(?:d['\u2019]expérience|d['\u2019]exp\.?|minimum|requis)", desc)
    if desc_exp:
        max_exp = max(int(x) for x in desc_exp)
        if max_exp >= 5:
            if "exp. requis" not in " ".join(reasons):
                reasons.append(f"{max_exp} ans d'exp. requis (description)")
                score -= 30
        elif max_exp >= 3:
            if "exp. requis" not in " ".join(reasons):
                reasons.append(f"{max_exp} ans d'exp. requis (limite)")
                score -= 10

    # Salaire trop eleve = poste senior
    sal_match = re.search(r"(\d+)\s*-\s*(\d+)", salary)
    if sal_match:
        sal_min = int(sal_match.group(1))
        if sal_min >= 60:
            reasons.append(f"Salaire eleve ({salary}) = senior")
            score -= 15

    # Stage
    if job.get("contract") == "Stage":
        reasons.append("Stage")
        score -= 40

    # --- Positifs ---

    matched_skills = [kw for kw in CORE_SKILLS if kw in all_text]
    if matched_skills:
        score += min(len(matched_skills) * 5, 30)

    if any(kw in all_text for kw in ["junior", "débutant", "jeune diplômé", "0-2 ans", "première expérience"]):
        score += 15
        reasons.append("Junior/debutant")

    if any(kw in all_text for kw in ["pme", "eti", "tpe", "familiale", "indépendante"]):
        score += 10

    if any(kw in title for kw in ["technico-commercial", "avant-vente", "sales engineer", "ingénieur commercial"]):
        score += 15

    # Bonus experience basse (champ WTTJ)
    if exp_min is not None:
        try:
            if float(exp_min) <= 1:
                score += 10
                if "Junior" not in " ".join(reasons):
                    reasons.append("Exp. minimum basse (WTTJ)")
        except (ValueError, TypeError):
            pass

    # --- Verdict ---
    score = max(0, min(100, score))

    if score >= 60:
        verdict = "A_POSTULER"
    elif score >= 40:
        verdict = "A_EXAMINER"
    else:
        verdict = "ELIMINEE"

    job["score"] = score
    job["verdict"] = verdict
    job["reasons"] = reasons
    job["matched_skills"] = matched_skills

    return job


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def generate_report(jobs: list[dict]) -> str:
    jobs_sorted = sorted(jobs, key=lambda j: j.get("score", 0), reverse=True)

    lines = [
        f"# Rapport WTTJ - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"**{len(jobs_sorted)} offres analysees**",
        f"- A postuler : {sum(1 for j in jobs_sorted if j.get('verdict') == 'A_POSTULER')}",
        f"- A examiner : {sum(1 for j in jobs_sorted if j.get('verdict') == 'A_EXAMINER')}",
        f"- Eliminees  : {sum(1 for j in jobs_sorted if j.get('verdict') == 'ELIMINEE')}",
        f"",
        "| Score | Verdict | Intitule | Entreprise | Lieu | Salaire | Contrat | Raisons | Lien |",
        "|-------|---------|----------|------------|------|---------|---------|---------|------|",
    ]

    for j in jobs_sorted:
        verdict_label = {"A_POSTULER": "A postuler", "A_EXAMINER": "A examiner", "ELIMINEE": "Eliminee"}.get(j["verdict"], "?")
        reasons_str = "; ".join(j.get("reasons", []))[:60]
        title = (j.get("title") or "?")[:45]
        company = (j.get("company") or "?")[:20]
        location = (j.get("location") or "?")[:20]
        salary = (j.get("salary") or "N/A")[:20]
        url = j.get("url", "")

        lines.append(
            f"| {j.get('score',0):3d} | {verdict_label} | {title} | {company} | {location} | {salary} | {j.get('contract','?')} | {reasons_str} | [Lien]({url}) |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Recherche et classement d'offres WTTJ (Welcome to the Jungle)")
    parser.add_argument("--queries", nargs="+", help="Mots-cles de recherche")
    parser.add_argument("--max", type=int, default=10, help="Nombre max d'offres par requete (defaut: 10)")
    parser.add_argument("--output", "-o", type=str, help="Fichier de sortie JSON")
    parser.add_argument("--report", "-r", type=str, help="Fichier de sortie rapport markdown")

    args = parser.parse_args()

    queries = args.queries or DEFAULT_QUERIES
    all_jobs = []
    seen_ids = set()

    for q in queries:
        print(f"Recherche: '{q}' ...", file=sys.stderr)
        results = search_jobs(q, count=args.max)
        new_count = 0
        for raw in results:
            job = parse_offre(raw)
            if job["job_id"] and job["job_id"] not in seen_ids:
                classified = classify_job(job)
                all_jobs.append(classified)
                seen_ids.add(job["job_id"])
                new_count += 1
        print(f"  {len(results)} resultats, {new_count} nouveaux", file=sys.stderr)

    print(f"\nTotal: {len(all_jobs)} offres uniques", file=sys.stderr)

    if not all_jobs:
        print("Aucune offre trouvee.", file=sys.stderr)
        return

    # Affichage classement
    for j in sorted(all_jobs, key=lambda x: x["score"], reverse=True):
        v = j["verdict"]
        s = j["score"]
        t = j.get("title", "?")[:50]
        c = j.get("company", "?")[:20]
        print(f"  {v} ({s:3d}) | {t} | {c}", file=sys.stderr)

    # Rapport
    report = generate_report(all_jobs)
    print(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, ensure_ascii=False, indent=2)
        print(f"\nJSON sauvegarde: {args.output}", file=sys.stderr)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Rapport sauvegarde: {args.report}", file=sys.stderr)


if __name__ == "__main__":
    main()
