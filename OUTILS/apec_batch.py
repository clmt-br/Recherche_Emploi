#!/usr/bin/env python3
"""
APEC Batch Search & Classifier
Recherche des offres APEC par mots-cles, les analyse et les classe
selon les criteres du profil candidat.

Aucune authentification requise - l'API APEC est publique.

Usage:
    python apec_batch.py                                  # Recherches par defaut (profil Clement)
    python apec_batch.py --queries "ingenieur mecanique" "technico-commercial"
    python apec_batch.py --max 30 --output rapport.json
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

APEC_BASE = "https://www.apec.fr"
SEARCH_URL = f"{APEC_BASE}/cms/webservices/rechercheOffre"

# Codes departements IDF
DEPS_IDF = ["75", "92", "93", "94", "95", "78", "91", "77"]

# Recherches par defaut
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

# Type contrat APEC codes
CONTRACT_TYPES = {
    101888: "CDI",
    101887: "CDD",
    101889: "Interim",
    101890: "Stage",
}

# ---------------------------------------------------------------------------
# Classification (memes listes que linkedin_batch.py)
# ---------------------------------------------------------------------------

PRESTA_KEYWORDS = [
    "consulting", "conseil en ingénierie", "assistance technique",
    "société de conseil", "esn", "ssii", "prestataire", "ingénierie externalisée",
    "délégation", "régie", "mise à disposition",
    "mise a disposition", "conseil en innovation",
    "bureau d'études externalisé", "prestations d'ingénierie",
]

# Endpoint detail offre
OFFER_DETAIL_URL = f"{APEC_BASE}/cms/webservices/offre/public"

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
    "global engineering systems", "g.e.s.", "ges ",
    "leaf ingenierie", "leaf ingénierie",
    "avantis", "proaxian", "terx", "sophia",
    "cleeven", "b-hive", "groupe lr", "vulcain",
]

ARMEMENT_KEYWORDS = [
    "armement", "défense militaire", "missile", "munition",
    "arme", "balistique", "pyrotechnie",
]

# Cabinets de recrutement / headhunters (PAS des ESN — CDI chez le client final)
# On ne les elimine pas, mais on signale que l'entreprise finale est masquee
RECRUITMENT_FIRMS = [
    "selescope", "recrutonsensemble", "handicap job", "talents immo",
    "michael page", "hays", "robert half", "spring", "page personnel",
    "expectra", "adecco", "randstad", "manpower", "keljob",
    "6e sens rh", "6ème sens", "lincoln", "robert walters",
    "gifemploi", "gif emploi",
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
# Session APEC
# ---------------------------------------------------------------------------

def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": f"{APEC_BASE}/candidat/recherche-emploi.html/emploi",
        "Origin": APEC_BASE,
    })
    # Visiter la page pour obtenir les cookies de session
    session.get(f"{APEC_BASE}/candidat/recherche-emploi.html/emploi", timeout=15)
    return session


# ---------------------------------------------------------------------------
# Detail offre (resolution entreprise)
# ---------------------------------------------------------------------------

def fetch_offer_details(session: requests.Session, numero_offre: str) -> dict | None:
    """Recupere les details complets d'une offre APEC via l'API publique.
    Retourne un dict avec les champs enrichis ou None si erreur."""
    try:
        time.sleep(random.uniform(0.3, 0.8))
        resp = session.get(
            OFFER_DETAIL_URL,
            params={"numeroOffre": numero_offre},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except (requests.RequestException, json.JSONDecodeError):
        return None


def extract_company_info(detail: dict) -> dict:
    """Extrait le nom reel de l'entreprise et detecte les presta
    depuis les champs enrichis de l'API detail."""
    info = {
        "real_company": "",
        "company_description": "",
        "candidature_url": "",
        "interlocuteur": "",
        "is_presta_from_detail": False,
        "presta_evidence": "",
        "actual_location": "",
    }

    if not detail:
        return info

    # Nom de l'etablissement (souvent le nom du recruteur/plateforme)
    nom_etablissement = detail.get("nomCompteEtablissement", "")

    # Texte de presentation entreprise (mine d'or)
    entreprise_html = detail.get("texteHtmlEntreprise", "")
    entreprise_clean = re.sub(r"<[^>]+>", " ", entreprise_html)
    entreprise_clean = re.sub(r"&[a-z]+;|&#x?[0-9a-f]+;", " ", entreprise_clean)
    entreprise_clean = re.sub(r"\s+", " ", entreprise_clean).strip()
    info["company_description"] = entreprise_clean[:500]

    # URL de candidature (revele souvent le vrai site)
    info["candidature_url"] = detail.get("adresseUrlCandidature", "") or ""

    # Interlocuteur
    prenom = detail.get("prenomInterlocuteur", "")
    nom = detail.get("nomInterlocuteur", "")
    if prenom or nom:
        info["interlocuteur"] = f"{prenom} {nom}".strip()

    # --- Resolution du nom reel ---
    # Priorite : nomCompteEtablissement (fiable) > regex sur description > URL

    # 1. nomCompteEtablissement = source la plus fiable (nom du compte APEC)
    # Ignorer les plateformes generiques qui ne sont pas le vrai recruteur
    generic_accounts = ["cadremploi", "apec", "indeed", "monster",
                        "jobposting", "engagement jeunes"]
    name_from_account = ""
    if nom_etablissement and nom_etablissement.lower() not in generic_accounts:
        name_from_account = nom_etablissement

    # 2. Chercher le nom dans la description entreprise
    name_from_desc = ""
    desc_lower = entreprise_clean.lower()
    if entreprise_clean:
        # Chercher dans tout le texte
        # Contextes ou un nom d'entreprise apparait :
        # debut de texte, apres un point, apres "Chez"
        name_pattern = re.compile(
            r"(?:^|(?:Chez|chez)\s+|(?<=\.\s))([A-Z][A-Za-zÀ-ÿ0-9\s&\-']{2,40}?)"
            r"(?:\s+est\b|\s+résulte\b|\s*,\s+(?:acteur|filiale|leader|partenaire|soci[eé]t[eé]|cabinet|groupe|sp[eé]ciali)"
            r"|\s+a\s+(?:été|pour|à coeur)"
            r"|\s+compte|\s+SAS\b|\s+SA\b|\s+SARL\b|\s+filiale\b)"
        )
        reject_starts = ("dans ", "notre ", "nous ", "le ", "la ", "les ",
                         "c'est ", "son ", "sa ", "ses ", "ce ", "sur ",
                         "avec ", "pour ", "en ", "une ", "un ", "il ",
                         "elle ", "qui ", "que ")
        for m in name_pattern.finditer(entreprise_clean[:800]):
            candidate = m.group(1).strip()
            if (len(candidate.split()) <= 5
                    and not candidate.lower().startswith(reject_starts)
                    and len(candidate) >= 3):
                name_from_desc = candidate
                break

    # 3. Nom depuis l'URL de candidature (domaine ou page Cadremploi)
    name_from_url = ""
    cand_url = info["candidature_url"]
    if cand_url and cand_url != "?":
        url_lower = cand_url.lower()
        generic_platforms = ["indeed.com", "apec.fr",
                            "welcometothejungle.com", "linkedin.com",
                            "engagement-jeunes.com", "jobposting.pro",
                            "monster.fr", "hellowork.com"]
        if "cadremploi.fr" in url_lower:
            # Tenter de recuperer le nom d'entreprise depuis la page Cadremploi
            try:
                resp = requests.get(cand_url, timeout=10, allow_redirects=True,
                                   headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    # Chercher le nom d'entreprise dans la page
                    # Cadremploi utilise souvent <meta property="og:title"> ou data-company
                    m_ce = re.search(r'(?:data-company["\s=]+|"company"\s*:\s*")["\s]*([^"<>]+)', resp.text)
                    if not m_ce:
                        # Fallback: chercher "Société : NOM" ou "Entreprise : NOM"
                        m_ce = re.search(r'(?:Soci[eé]t[eé]|Entreprise|Recruteur)\s*:\s*</?\w*>?\s*([^<\n]{3,50})', resp.text)
                    if m_ce:
                        name_from_url = m_ce.group(1).strip()
            except requests.RequestException:
                pass
        elif not any(p in url_lower for p in generic_platforms):
            m_url = re.search(r"https?://(?:www\.)?([a-z0-9\-]+)\.", url_lower)
            if m_url:
                raw_name = m_url.group(1).replace("-", " ").title()
                if raw_name.lower() not in ["wd3", "jobs", "careers", "apply", "greenhouse"]:
                    name_from_url = raw_name

    # 4. Construire le nom reel (priorite : compte > desc > url)
    if name_from_account:
        info["real_company"] = name_from_account
    elif name_from_desc:
        info["real_company"] = name_from_desc
    elif name_from_url:
        info["real_company"] = name_from_url
    elif nom_etablissement:
        # Plateforme generique = entreprise non identifiee
        info["real_company"] = f"[? DEMANDER - via {nom_etablissement}]"
    else:
        info["real_company"] = "[? DEMANDER]"

    # --- Detection presta dans la description entreprise ---
    presta_in_desc = [kw for kw in PRESTA_KEYWORDS if kw in desc_lower]
    presta_in_name = [kw for kw in PRESTA_COMPANIES if kw in info["real_company"].lower()]
    presta_in_etablissement = [kw for kw in PRESTA_COMPANIES if kw in nom_etablissement.lower()]

    if presta_in_desc or presta_in_name or presta_in_etablissement:
        info["is_presta_from_detail"] = True
        evidence = presta_in_desc + presta_in_name + presta_in_etablissement
        info["presta_evidence"] = ", ".join(evidence[:3])

    # --- Detection cabinet de recrutement (pas ESN, juste intermediaire) ---
    real_lower = info["real_company"].lower()
    etab_lower = nom_etablissement.lower()
    is_recruiter = any(kw in real_lower or kw in etab_lower for kw in RECRUITMENT_FIRMS)
    if is_recruiter:
        info["real_company"] = f"[? DEMANDER - cabinet {info['real_company']}]"

    # --- Localisation reelle (parfois differente du champ lieux) ---
    # Chercher dans le texte de l'offre
    texte_offre = detail.get("texteHtml", "") or ""
    texte_profil = detail.get("texteHtmlProfil", "") or ""
    full_text = f"{texte_offre} {texte_profil}"
    loc_match = re.search(
        r"(?:localisé|basé|situé|implanté)\s+(?:à|a)\s+([A-ZÀ-Ÿ][a-zà-ÿA-ZÀ-Ÿ\s\-']+)\s*\((\d{2,5})\)",
        full_text
    )
    if loc_match:
        info["actual_location"] = f"{loc_match.group(1).strip()} ({loc_match.group(2)})"

    return info


# ---------------------------------------------------------------------------
# Recherche APEC
# ---------------------------------------------------------------------------

def search_jobs(session: requests.Session, query: str, count: int = 25,
                departments: list[str] = None) -> list[dict]:
    """Recherche APEC et retourne la liste des offres."""
    if departments is None:
        departments = DEPS_IDF

    all_results = []
    start = 0
    batch_size = min(count, 50)

    while start < count:
        payload = {
            "motsCles": query,
            "lieux": departments,
            "sorts": [{"type": "DATE", "direction": "DESCENDING"}],
            "pagination": {"startIndex": start, "range": batch_size},
            "activeFiltre": True,
        }

        time.sleep(random.uniform(0.5, 1.5))
        try:
            resp = session.post(SEARCH_URL, json=payload, timeout=15)
        except requests.RequestException as e:
            print(f"  Erreur reseau: {e}", file=sys.stderr)
            break

        if resp.status_code != 200:
            print(f"  Erreur HTTP {resp.status_code} pour '{query}'", file=sys.stderr)
            break

        data = resp.json()
        results = data.get("resultats", [])
        total = data.get("totalCount", 0)

        if not results:
            break

        all_results.extend(results)
        start += batch_size

        if start >= total or start >= count:
            break

    return all_results[:count]


def parse_offre(raw: dict) -> dict:
    """Convertit une offre APEC brute en format standardise."""
    offre_id = raw.get("id", 0)
    numero_offre = raw.get("numeroOffre", str(offre_id))
    contract_code = raw.get("typeContrat")
    contract = CONTRACT_TYPES.get(contract_code, str(contract_code) if contract_code else "?")

    return {
        "job_id": str(offre_id),
        "numero_offre": numero_offre,
        "source": "APEC",
        "url": f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/{numero_offre}",
        "title": raw.get("intitule", ""),
        "company": raw.get("nomCommercial", ""),
        "location": raw.get("lieuTexte", ""),
        "salary": raw.get("salaireTexte", ""),
        "contract": contract,
        "description": raw.get("texteOffre", ""),
        "listed_date": (raw.get("datePublication") or "")[:10],
        "confidential": raw.get("offreConfidentielle", False),
        # Champs enrichis (remplis par enrich_job)
        "real_company": "",
        "company_description": "",
        "candidature_url": "",
        "interlocuteur": "",
        "is_presta_from_detail": False,
        "presta_evidence": "",
        "actual_location": "",
    }


def enrich_job(session: requests.Session, job: dict) -> dict:
    """Enrichit une offre avec les details de l'API publique
    (nom reel entreprise, detection presta, URL candidature)."""
    numero = job.get("numero_offre", "")
    if not numero:
        return job

    detail = fetch_offer_details(session, numero)
    if not detail:
        return job

    info = extract_company_info(detail)
    job.update(info)

    # Si le champ company etait vide, le remplacer par le nom reel
    if not job["company"] and info["real_company"]:
        job["company"] = info["real_company"]

    # Enrichir la description avec le texte entreprise pour le scoring
    if info["company_description"]:
        job["description"] = (job.get("description") or "") + " " + info["company_description"]

    return job


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
    # Detection enrichie via les details de l'offre
    if job.get("is_presta_from_detail"):
        is_presta = True
        evidence = job.get("presta_evidence", "")
        real_name = job.get("real_company", "")
        if "Presta" not in " ".join(reasons):
            reasons.append(f"Presta detecte ({real_name}: {evidence})")
    if is_presta:
        score -= 40

    # Localisation reelle differente du champ lieux APEC
    actual_loc = job.get("actual_location", "")
    if actual_loc:
        # Verifier si le departement est en IDF
        dep_match = re.search(r"\((\d{2,5})\)", actual_loc)
        if dep_match:
            dep = dep_match.group(1)[:2]
            if dep not in ["75", "92", "93", "94", "95", "78", "91", "77"]:
                reasons.append(f"Localisation reelle hors IDF ({actual_loc})")
                score -= 50

    # Armement
    if any(kw in all_text for kw in ARMEMENT_KEYWORDS):
        reasons.append("Secteur armement")
        score -= 50

    # Hors profil
    if any(kw in all_text for kw in OUT_OF_SCOPE):
        matched = [kw for kw in OUT_OF_SCOPE if kw in all_text]
        reasons.append(f"Hors profil ({', '.join(matched[:2])})")
        score -= 30

    # Confidentielle (pas de nom d'entreprise = impossible a verifier si presta)
    if job.get("confidential") and not company:
        reasons.append("Offre confidentielle")
        score -= 5

    # Experience dans la description
    desc_exp = re.findall(r"(\d+)\s*(?:ans?|années?)\s*(?:d['\u2019]expérience|d['\u2019]exp\.?|minimum|requis)", desc)
    if desc_exp:
        max_exp = max(int(x) for x in desc_exp)
        if max_exp >= 5:
            reasons.append(f"{max_exp} ans d'exp. requis")
            score -= 30
        elif max_exp >= 3:
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
        f"# Rapport APEC - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"**{len(jobs_sorted)} offres analysees**",
        f"- A postuler : {sum(1 for j in jobs_sorted if j.get('verdict') == 'A_POSTULER')}",
        f"- A examiner : {sum(1 for j in jobs_sorted if j.get('verdict') == 'A_EXAMINER')}",
        f"- Eliminees  : {sum(1 for j in jobs_sorted if j.get('verdict') == 'ELIMINEE')}",
        f"",
        "| Score | Verdict | Intitule | Entreprise | Lieu | Salaire | Raisons | Lien | Postuler |",
        "|-------|---------|----------|------------|------|---------|---------|------|----------|",
    ]

    for j in jobs_sorted:
        verdict_label = {"A_POSTULER": "A postuler", "A_EXAMINER": "A examiner", "ELIMINEE": "Eliminee"}.get(j["verdict"], "?")
        reasons_str = "; ".join(j.get("reasons", []))[:80]
        title = (j.get("title") or "?")[:45]
        # Nom reel de l'entreprise (enrichi) > nom commercial > Confidentiel
        company = j.get("real_company") or j.get("company") or "Confidentiel"
        company = company[:25]
        location = (j.get("location") or "?")[:20]
        actual_loc = j.get("actual_location", "")
        if actual_loc and actual_loc != location:
            location = f"{actual_loc}"[:20]
        salary = (j.get("salary") or "N/A")[:20]
        url = j.get("url", "")
        cand_url = j.get("candidature_url", "")
        cand_link = f"[Postuler]({cand_url})" if cand_url and cand_url != "?" else "-"

        lines.append(
            f"| {j.get('score',0):3d} | {verdict_label} | {title} | {company} | {location} | {salary} | {reasons_str} | [Voir]({url}) | {cand_link} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Recherche et classement d'offres APEC")
    parser.add_argument("--queries", nargs="+", help="Mots-cles de recherche")
    parser.add_argument("--max", type=int, default=10, help="Nombre max d'offres par requete (defaut: 10)")
    parser.add_argument("--output", "-o", type=str, help="Fichier de sortie JSON")
    parser.add_argument("--report", "-r", type=str, help="Fichier de sortie rapport markdown")

    args = parser.parse_args()

    session = get_session()
    print("Session APEC OK (aucune auth requise)", file=sys.stderr)

    queries = args.queries or DEFAULT_QUERIES
    all_jobs = []
    seen_ids = set()

    for q in queries:
        print(f"Recherche: '{q}' ...", file=sys.stderr)
        results = search_jobs(session, q, count=args.max)
        new_count = 0
        for raw in results:
            job = parse_offre(raw)
            if job["job_id"] not in seen_ids:
                seen_ids.add(job["job_id"])
                new_count += 1
                all_jobs.append(job)
        print(f"  {len(results)} resultats, {new_count} nouveaux", file=sys.stderr)

    # Enrichissement : recuperer les details de chaque offre pour
    # identifier l'entreprise reelle et detecter les presta
    print(f"\nEnrichissement de {len(all_jobs)} offres (details API)...", file=sys.stderr)
    for i, job in enumerate(all_jobs):
        job = enrich_job(session, job)
        all_jobs[i] = job
        real = job.get("real_company", "")
        if real:
            print(f"  [{i+1}/{len(all_jobs)}] {job['title'][:40]} -> {real}", file=sys.stderr)
        else:
            print(f"  [{i+1}/{len(all_jobs)}] {job['title'][:40]} -> (non resolu)", file=sys.stderr)

    # Classification apres enrichissement
    for i, job in enumerate(all_jobs):
        all_jobs[i] = classify_job(job)

    print(f"\nTotal: {len(all_jobs)} offres uniques", file=sys.stderr)

    if not all_jobs:
        print("Aucune offre trouvee.", file=sys.stderr)
        return

    # Affichage classement
    for j in sorted(all_jobs, key=lambda x: x["score"], reverse=True):
        v = j["verdict"]
        s = j["score"]
        t = j.get("title", "?")[:50]
        c = j.get("real_company") or j.get("company") or "?"
        c = c[:25]
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
