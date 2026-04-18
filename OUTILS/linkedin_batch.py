#!/usr/bin/env python3
"""
LinkedIn Batch Search & Classifier
Recherche des offres LinkedIn par mots-cles, les analyse et les classe
selon les criteres du profil candidat.

Usage:
    python linkedin_batch.py                              # Recherches par defaut (profil Clement)
    python linkedin_batch.py --queries "ingenieur mecanique" "technico-commercial"
    python linkedin_batch.py --urls urls.txt              # Batch depuis un fichier d'URLs
    python linkedin_batch.py --max 30 --days 7            # 30 offres max, 7 derniers jours
    python linkedin_batch.py --output rapport.json        # Sauvegarder le rapport
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
# Constantes
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
COOKIE_FILE = SCRIPT_DIR / ".linkedin_cookie"

VOYAGER_BASE = "https://www.linkedin.com/voyager/api"

# GeoID Ile-de-France
GEO_IDF = "104246759"

# Recherches par defaut - ciblent le profil de Clement
DEFAULT_QUERIES = [
    "ingénieur mécanique junior",
    "ingénieur bureau d'études mécanique",
    "ingénieur méthodes industrialisation",
    "ingénieur mécatronique",
    "technico-commercial ingénieur",
    "ingénieur qualité normalisation",
    "chef de projet technique junior",
    "ingénieur conception mécanique",
    "ingénieur automatisme GTB",
    "ingénieur automaticien CVC",
    "ingénieur supervision bâtiment",
]

# Filtres temps (LinkedIn API values)
TIME_FILTERS = {
    1: "r86400",       # 24h
    7: "r604800",      # 7 jours
    30: "r2592000",    # 30 jours
}

# ---------------------------------------------------------------------------
# Mots-cles pour la classification
# ---------------------------------------------------------------------------

# Indicateurs de societe de presta/ESN
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
]

# Indicateurs d'armement
ARMEMENT_KEYWORDS = [
    "armement", "défense militaire", "missile", "munition",
    "arme", "balistique", "pyrotechnie",
]

# Competences coeur de Clement
CORE_SKILLS = [
    "mécanique", "conception", "cao", "catia", "solidworks",
    "cotation", "gps", "iso", "dessin technique", "mise en plan",
    "gestion de projet", "bureau d'études", "méthodes",
    "industrialisation", "qualité", "normalisation",
    "technico-commercial", "avant-vente", "ingénieur commercial",
    "mécatronique", "robotique", "python", "automatisme",
]

# Competences hors profil
OUT_OF_SCOPE = [
    "génie civil", "btp", "bâtiment", "charpente",
    "génie électrique pur", "haute tension", "transformateur",
    "sûreté physique", "incendie",
    "développeur", "data scientist", "devops",
    "infirmier", "médecin", "pharmacien",
    "comptable", "juriste", "avocat",
]


# ---------------------------------------------------------------------------
# Session LinkedIn
# ---------------------------------------------------------------------------

def get_session() -> requests.Session:
    li_at = COOKIE_FILE.read_text(encoding="utf-8").strip() if COOKIE_FILE.exists() else ""
    if not li_at:
        print("ERREUR: pas de cookie LinkedIn. Lancez: python linkedin_scraper.py --setup", file=sys.stderr)
        sys.exit(1)

    session = requests.Session()
    jsid = f"ajax:{random.randint(1000000, 9999999)}"
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/vnd.linkedin.normalized+json+2.1",
        "x-restli-protocol-version": "2.0.0",
        "csrf-token": jsid,
        "x-li-lang": "fr_FR",
    })
    session.cookies.set("li_at", li_at, domain=".linkedin.com")
    session.cookies.set("JSESSIONID", f'"{jsid}"', domain=".linkedin.com")
    return session


# ---------------------------------------------------------------------------
# Recherche d'offres
# ---------------------------------------------------------------------------

def search_jobs(session: requests.Session, query: str, count: int = 25,
                geo_id: str = GEO_IDF, days: int = 7) -> list[str]:
    """Recherche LinkedIn et retourne une liste de job IDs."""
    time_filter = TIME_FILTERS.get(days, f"r{days * 86400}")

    # Construire l'URL manuellement pour eviter le double-encodage par requests
    from urllib.parse import quote
    base = f"{VOYAGER_BASE}/voyagerJobsDashJobCards"
    kw_encoded = quote(query)
    query_part = f"(origin:JOB_SEARCH_PAGE_SEARCH_BUTTON,keywords:{kw_encoded},locationUnion:(geoId:{geo_id}),selectedFilters:(timePostedRange:List({time_filter})))"

    all_ids = []
    fetched = 0

    while fetched < count:
        batch_count = min(25, count - fetched)
        full_url = (
            f"{base}?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-227"
            f"&count={batch_count}&q=jobSearch&query={query_part}&start={fetched}"
        )

        time.sleep(random.uniform(1.0, 2.0))
        try:
            resp = session.get(full_url, timeout=15)
        except requests.RequestException as e:
            print(f"  Erreur reseau: {e}", file=sys.stderr)
            break

        if resp.status_code != 200:
            print(f"  Erreur recherche HTTP {resp.status_code} pour '{query}'", file=sys.stderr)
            break

        data = resp.json()
        included = data.get("included", [])

        # Extraire les job IDs
        batch_ids = []
        for item in included:
            if item.get("$type", "").endswith("JobPosting"):
                urn = item.get("entityUrn", "")
                jid = urn.split(":")[-1]
                if jid and jid not in all_ids:
                    batch_ids.append(jid)

        if not batch_ids:
            break

        all_ids.extend(batch_ids)
        fetched += batch_count

        # Verifier s'il y a plus de pages
        paging = data.get("data", {}).get("paging", {})
        total = paging.get("total", 0)
        if fetched >= total:
            break

    return all_ids


# ---------------------------------------------------------------------------
# Details d'une offre (Voyager API)
# ---------------------------------------------------------------------------

def _ts_to_date(ts) -> str | None:
    if ts and isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    return None


def _resolve_urn(included: list, urn: str, field: str = "name") -> str | None:
    for item in included:
        if item.get("entityUrn") == urn or item.get("$id") == urn:
            return item.get(field)
    return None


def fetch_job_details(session: requests.Session, job_id: str) -> dict | None:
    """Recupere les details d'une offre via Voyager API."""
    time.sleep(random.uniform(0.5, 1.5))
    url = f"{VOYAGER_BASE}/jobs/jobPostings/{job_id}"

    try:
        resp = session.get(url, timeout=15)
    except requests.RequestException:
        return None

    if resp.status_code == 429:
        print("  Rate-limit LinkedIn. Pause 30s...", file=sys.stderr)
        time.sleep(30)
        try:
            resp = session.get(url, timeout=15)
        except requests.RequestException:
            return None

    if resp.status_code != 200:
        return None

    payload = resp.json()
    d = payload.get("data", {})
    included = payload.get("included", [])

    # Company
    company_urn = (d.get("companyDetails") or {}).get("company", "")
    company = _resolve_urn(included, company_urn)
    if not company:
        for item in included:
            if "company" in item.get("$type", "").lower() and item.get("name"):
                company = item["name"]
                break
    if not company:
        slug = d.get("urlPathSegment", "")
        m = re.search(r"-at-(.+?)-\d+$", slug)
        if m:
            company = m.group(1).replace("-", " ").title()

    # Employment type
    emp_map = {
        "FULL_TIME": "CDI",
        "PART_TIME": "Temps partiel",
        "CONTRACT": "CDD",
        "INTERNSHIP": "Stage",
        "TEMPORARY": "Interim",
    }
    emp_status = (d.get("employmentStatus") or "").split(":")[-1]
    contract = emp_map.get(emp_status, emp_status)

    desc_text = (d.get("description") or {}).get("text", "")
    company_desc = (d.get("companyDescription") or {}).get("text", "")

    return {
        "job_id": job_id,
        "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        "title": d.get("title", ""),
        "company": company or "?",
        "location": d.get("formattedLocation", ""),
        "contract": contract,
        "experience_level": d.get("formattedExperienceLevel", ""),
        "listed_date": _ts_to_date(d.get("listedAt")),
        "expire_date": _ts_to_date(d.get("expireAt")),
        "description": desc_text,
        "company_description": company_desc,
        "industries": d.get("formattedIndustries"),
    }


# ---------------------------------------------------------------------------
# Classificateur
# ---------------------------------------------------------------------------

def classify_job(job: dict) -> dict:
    """Classe une offre selon les criteres du profil candidat.
    Retourne le job enrichi avec verdict, raison et score."""

    title = (job.get("title") or "").lower()
    company = (job.get("company") or "").lower()
    desc = (job.get("description") or "").lower()
    company_desc = (job.get("company_description") or "").lower()
    exp = (job.get("experience_level") or "").lower()
    location = (job.get("location") or "").lower()
    all_text = f"{title} {desc} {company_desc}"

    reasons = []
    score = 50  # Score de base

    # --- Criteres eliminatoires ---

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

    # Hors IDF
    if location and "france" in location and not any(x in location for x in ["île-de-france", "ile-de-france", "paris", "idf", "hauts-de-seine", "val-d'oise", "seine", "yvelines", "essonne", "val-de-marne"]):
        reasons.append(f"Hors IDF ({job.get('location')})")
        score -= 50

    # Experience trop elevee
    exp_years = None
    m = re.search(r"(\d+)", exp)
    if m:
        exp_years = int(m.group(1))
    if "confirmé" in exp or "senior" in exp or "experienced" in exp:
        exp_years = exp_years or 4
    if "directeur" in exp or "director" in exp or "executive" in exp:
        exp_years = exp_years or 8

    # Chercher "X ans d'expérience" dans la description
    desc_exp = re.findall(r"(\d+)\s*(?:ans?|années?)\s*(?:d['\u2019]expérience|d['\u2019]exp\.?|minimum)", desc)
    if desc_exp:
        max_exp = max(int(x) for x in desc_exp)
        if max_exp >= 5:
            reasons.append(f"{max_exp} ans d'exp. requis dans description")
            score -= 30

    if exp_years and exp_years >= 5:
        reasons.append(f"Niveau exp. trop eleve ({job.get('experience_level')})")
        score -= 30

    # Hors profil
    if any(kw in all_text for kw in OUT_OF_SCOPE):
        matched = [kw for kw in OUT_OF_SCOPE if kw in all_text]
        reasons.append(f"Hors profil ({', '.join(matched[:2])})")
        score -= 30

    # Stage
    if job.get("contract") == "Stage":
        reasons.append("Stage")
        score -= 40

    # --- Criteres positifs ---

    # Competences coeur
    matched_skills = [kw for kw in CORE_SKILLS if kw in all_text]
    if matched_skills:
        score += min(len(matched_skills) * 5, 30)

    # Junior / debutant
    if any(kw in all_text for kw in ["junior", "débutant", "jeune diplômé", "0-2 ans", "première expérience"]):
        score += 15
        reasons.append("Junior/debutant")

    # PME/ETI (bonus)
    if any(kw in all_text for kw in ["pme", "eti", "tpe", "familiale", "indépendante"]):
        score += 10

    # Technico-commercial (cible prioritaire)
    if any(kw in title for kw in ["technico-commercial", "avant-vente", "sales engineer", "ingénieur commercial"]):
        score += 15

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
    """Genere un rapport markdown avec tableau de classement."""
    # Trier par score decroissant
    jobs_sorted = sorted(jobs, key=lambda j: j.get("score", 0), reverse=True)

    lines = [
        f"# Rapport LinkedIn - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"**{len(jobs_sorted)} offres analysees**",
        f"- A postuler : {sum(1 for j in jobs_sorted if j.get('verdict') == 'A_POSTULER')}",
        f"- A examiner : {sum(1 for j in jobs_sorted if j.get('verdict') == 'A_EXAMINER')}",
        f"- Eliminees  : {sum(1 for j in jobs_sorted if j.get('verdict') == 'ELIMINEE')}",
        f"",
        "| Score | Verdict | Intitule | Entreprise | Lieu | Contrat | Exp. | Raisons | Lien |",
        "|-------|---------|----------|------------|------|---------|------|---------|------|",
    ]

    for j in jobs_sorted:
        verdict_emoji = {"A_POSTULER": "A postuler", "A_EXAMINER": "A examiner", "ELIMINEE": "Eliminee"}.get(j["verdict"], "?")
        reasons_str = "; ".join(j.get("reasons", []))[:60]
        title = (j.get("title") or "?")[:45]
        company = (j.get("company") or "?")[:20]
        location = (j.get("location") or "?")[:25]
        exp = (j.get("experience_level") or "?")[:15]
        url = j.get("url", "")

        lines.append(
            f"| {j.get('score',0):3d} | {verdict_emoji} | {title} | {company} | {location} | {j.get('contract','?')} | {exp} | {reasons_str} | [Lien]({url}) |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Recherche et classement d'offres LinkedIn")
    parser.add_argument("--queries", nargs="+", help="Mots-cles de recherche (defaut: profil Clement)")
    parser.add_argument("--urls", type=str, help="Fichier texte contenant des URLs LinkedIn (une par ligne)")
    parser.add_argument("--max", type=int, default=10, help="Nombre max d'offres par requete (defaut: 10)")
    parser.add_argument("--days", type=int, default=7, help="Anciennete max en jours (defaut: 7)")
    parser.add_argument("--output", "-o", type=str, help="Fichier de sortie JSON")
    parser.add_argument("--report", "-r", type=str, help="Fichier de sortie rapport markdown")
    parser.add_argument("--no-details", action="store_true", help="Ne pas recuperer les details (rapide)")

    args = parser.parse_args()

    session = get_session()
    print("Session LinkedIn OK", file=sys.stderr)

    all_job_ids = []
    seen_ids = set()

    # Mode URLs
    if args.urls:
        with open(args.urls, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.search(r"(\d{8,})", line)
                if m:
                    jid = m.group(1)
                    if jid not in seen_ids:
                        all_job_ids.append(jid)
                        seen_ids.add(jid)
        print(f"{len(all_job_ids)} URLs chargees", file=sys.stderr)

    # Mode recherche
    else:
        queries = args.queries or DEFAULT_QUERIES
        for q in queries:
            print(f"Recherche: '{q}' ...", file=sys.stderr)
            ids = search_jobs(session, q, count=args.max, days=args.days)
            new_ids = [jid for jid in ids if jid not in seen_ids]
            for jid in new_ids:
                all_job_ids.append(jid)
                seen_ids.add(jid)
            print(f"  {len(ids)} resultats, {len(new_ids)} nouveaux", file=sys.stderr)

    print(f"\nTotal: {len(all_job_ids)} offres uniques", file=sys.stderr)

    if not all_job_ids:
        print("Aucune offre trouvee.", file=sys.stderr)
        return

    # Recuperer les details
    jobs = []
    if args.no_details:
        # Mode rapide: juste les IDs sans details
        for jid in all_job_ids:
            jobs.append({"job_id": jid, "url": f"https://www.linkedin.com/jobs/view/{jid}/"})
    else:
        total = len(all_job_ids)
        for i, jid in enumerate(all_job_ids):
            print(f"  [{i+1}/{total}] Offre {jid}...", file=sys.stderr)
            details = fetch_job_details(session, jid)
            if details:
                classified = classify_job(details)
                jobs.append(classified)
                # Affichage rapide
                v = classified["verdict"]
                s = classified["score"]
                t = classified.get("title", "?")[:50]
                c = classified.get("company", "?")[:20]
                print(f"         {v} ({s}) | {t} | {c}", file=sys.stderr)
            else:
                print(f"         ERREUR recup details", file=sys.stderr)

    # Generer le rapport
    report = generate_report(jobs)
    print(report)

    # Sauvegarder JSON
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
        print(f"\nJSON sauvegarde: {args.output}", file=sys.stderr)

    # Sauvegarder rapport markdown
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Rapport sauvegarde: {args.report}", file=sys.stderr)


if __name__ == "__main__":
    main()
