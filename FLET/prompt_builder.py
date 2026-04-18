"""Construction du system prompt et du user prompt injectes au Claude Agent SDK.

Le system prompt est l'equivalent dynamique du CLAUDE.md, mais rendu depuis
profile.yaml de l'utilisateur courant. Ainsi chaque user a son contexte sans
modifier de fichier projet et l'app reste exportable.

Structure du system prompt :
    1. Mission generale
    2. Profil candidat (identite, formation, experiences, interets)
    3. Profil et ambitions, cibles d'emploi, exclusions
    4. Cadres de positionnement (GTB, ...) avec declencheurs
    5. Regles de redaction (forbidden phrases, accents, tirets)
    6. Banque anti-repetition (formulations deja utilisees)
    7. Outils disponibles
    8. Methodologie attendue
    9. Format de sortie JSON
"""
from pathlib import Path
from typing import Optional


# ============================================================
# Helpers de rendu par section
# ============================================================

def _render_identite(p: dict) -> str:
    ident = p.get("identite", {})
    lines = ["### Identite"]
    for label, key in [
        ("Nom", "nom"), ("Email", "email"), ("Telephone", "telephone"),
        ("Localisation", "localisation"), ("Mobilite", "mobilite"),
        ("Disponibilite", "disponibilite"),
    ]:
        v = ident.get(key, "")
        if v:
            lines.append(f"- {label} : {v}")
    return "\n".join(lines)


def _render_formation(p: dict) -> str:
    f = p.get("formation", {})
    lines = ["### Formation"]
    for label, key in [
        ("Ecole", "ecole"), ("Cursus", "cursus"),
        ("Prepa", "prepa"), ("International", "international"),
        ("Specialite", "specialite"), ("Contenu cursus", "contenu_cursus"),
    ]:
        v = f.get(key, "")
        if v:
            lines.append(f"- {label} : {v}")
    return "\n".join(lines)


def _render_experiences(p: dict) -> str:
    """Une experience par bloc, ordonnee par niveau_mise_en_avant."""
    exps = p.get("experiences", [])
    if not exps:
        return ""
    order = {"maximiser": 0, "mentionner": 1, "minimiser": 2}
    sorted_exps = sorted(exps, key=lambda e: order.get(e.get("niveau_mise_en_avant", "mentionner"), 1))

    out = ["### Experiences professionnelles\n"]
    for e in sorted_exps:
        niveau = e.get("niveau_mise_en_avant", "mentionner").upper()
        ent = e.get("entreprise", "?")
        lieu = e.get("lieu", "")
        per = e.get("periode", "")
        contract = e.get("type_contrat", "")
        header = f"#### {ent}"
        if lieu:
            header += f" - {lieu}"
        if per:
            header += f" ({per})"
        header += f" - **{niveau}**"
        out.append(header)
        if contract:
            out.append(f"- Contrat : {contract}")
        if e.get("contexte"):
            out.append(f"- Contexte : {e['contexte']}")
        if e.get("mission"):
            out.append(f"- Mission : {e['mission']}")
        if e.get("methodologie"):
            out.append(f"- Methodologie : {e['methodologie']}")
        if e.get("competences"):
            out.append(f"- Competences : {', '.join(e['competences'])}")
        if e.get("referentiels"):
            out.append(f"- Referentiels : {', '.join(e['referentiels'])}")
        if e.get("notes"):
            out.append(f"- **Notes IMPORTANTES** : {e['notes']}")

        if niveau == "MINIMISER":
            out.append("- *Cette experience est a minimiser : ne la mentionner que si vraiment pertinente.*")
        out.append("")
    return "\n".join(out).rstrip()


def _render_interets(p: dict) -> str:
    interets = p.get("interets_complementaires", [])
    if not interets:
        return ""
    out = ["### Interets complementaires (a mentionner SI pertinent_si match l'offre)\n"]
    for i in interets:
        out.append(f"#### {i.get('titre', '?')}")
        if i.get("description"):
            out.append(f"- {i['description']}")
        if i.get("competences"):
            out.append(f"- Competences : {', '.join(i['competences'])}")
        if i.get("pertinent_si"):
            out.append(f"- **Mentionner SI** l'offre touche a : {i['pertinent_si']}")
        out.append("")
    return "\n".join(out).rstrip()


def _render_ambitions_cibles(p: dict) -> str:
    out = ["## Profil, ambitions et cibles\n"]

    a = p.get("profil_ambitions", {})
    if a:
        if a.get("cible_prioritaire_taille"):
            out.append(f"- Cible prioritaire : {a['cible_prioritaire_taille']}"
                       + (f" ({a.get('raison_cible')})" if a.get("raison_cible") else ""))
        if a.get("ouverture_postes"):
            out.append(f"- Ouvert a : {', '.join(a['ouverture_postes'])}")
        if a.get("contexte_depart"):
            out.append(f"- Contexte depart : {a['contexte_depart']}")
        if a.get("esn_presta"):
            out.append(f"- ESN/presta : {a['esn_presta']}")

    c = p.get("cibles", {})
    if c:
        out.append("")
        if c.get("postes_a_conserver"):
            out.append("**Postes cibles a conserver :**")
            for poste in c["postes_a_conserver"]:
                out.append(f"  - {poste}")
        if c.get("exclusions_strictes"):
            out.append("\n**Exclusions strictes :**")
            for excl in c["exclusions_strictes"]:
                out.append(f"  - {excl}")
        if c.get("exception_intitule_commercial"):
            out.append(f"\n**Exception** : {c['exception_intitule_commercial']}")
        if c.get("zone_prioritaire"):
            out.append(f"\n- Zone prioritaire : {c['zone_prioritaire']}")
        if c.get("zone_acceptable"):
            out.append(f"- Zone acceptable : {c['zone_acceptable']}")
    return "\n".join(out)


def _render_cadres(p: dict) -> str:
    cadres = p.get("cadres_positionnement", [])
    if not cadres:
        return ""
    out = ["## Cadres de positionnement specifiques\n",
           "Si l'offre matche les declencheurs d'un cadre ci-dessous, "
           "applique STRICTEMENT les regles du cadre lors de la redaction CV/LM.\n"]
    for cadre in cadres:
        out.append(f"### Cadre : {cadre.get('nom', '?')}")
        if cadre.get("declencheurs"):
            out.append(f"**Declencheurs (mots dans l'offre)** : {', '.join(cadre['declencheurs'])}")
        if cadre.get("motivation"):
            out.append(f"\n**Motivation a restituer dans la LM** :\n> {cadre['motivation']}")
        if cadre.get("acquis_theoriques"):
            out.append("\n**Acquis theoriques (citables comme connaissances de cours/TP)** :")
            for a in cadre["acquis_theoriques"]:
                out.append(f"- {a}")
        if cadre.get("acquis_pratiques"):
            out.append("\n**Acquis pratiques (citables comme experiences personnelles concretes)** :")
            for a in cadre["acquis_pratiques"]:
                out.append(f"- {a}")
        if cadre.get("regles_strictes"):
            out.append("\n**REGLES STRICTES (a respecter sans exception)** :")
            for r in cadre["regles_strictes"]:
                out.append(f"- {r}")
        out.append("")
    return "\n".join(out).rstrip()


def _render_regles_redaction(p: dict) -> str:
    r = p.get("regles_redaction", {})
    out = ["## Regles de redaction (CRITIQUES)\n"]

    if r.get("ne_jamais_dire"):
        out.append("### Phrases interdites (ne jamais ecrire) :")
        for ph in r["ne_jamais_dire"]:
            out.append(f"- INTERDIT : `{ph}`")
        out.append("")

    if r.get("vocabulaire_specifique"):
        out.append("### Vocabulaire specifique (formulations exactes) :")
        for v in r["vocabulaire_specifique"]:
            out.append(f"- {v}")
        out.append("")

    if r.get("tirets_long_interdits"):
        out.append("### Tirets - regles strictes")
        out.append("- INTERDIT : em dash (---), en dash (--), tirets longs sous toute forme.")
        out.append("- Tex/LaTeX : utiliser UNIQUEMENT `-` (tiret-signe-moins simple).")
        out.append("  `--` produit un en dash interdit, `---` produit un em dash interdit.")
        out.append("- DOCX : verifier dans le XML python-docx absence de `&#x2014;` et `&#x2013;`.")
        out.append("- Si tu hesites : utiliser une virgule, deux-points, ou reformuler.")
        out.append("")

    if r.get("accents_obligatoires"):
        out.append("### Accents francais (obligatoires)")
        out.append("- Tous les accents `e a e e c u i o` doivent etre presents et corrects.")
        out.append("- Apostrophes typographiques : `&#x2019;` (jamais l'apostrophe droite `'`) dans le DOCX.")
        out.append("- Deux-points et point-virgule precedes d'une espace insecable `&#xa0;` dans le DOCX.")
        out.append("- Verifier specifiquement avant livraison : Clement, etudes, referentiels, ingenieurs, qualite, immediatement, federe, concretement, differents, specialiste, La Defense.")
        out.append("")

    return "\n".join(out).rstrip()


def _render_banque_formulations(formulations: list[dict]) -> str:
    """Rend les formulations deja utilisees pour interdire leur reutilisation."""
    out = [
        "## Banque anti-repetition (formulations DEJA UTILISEES)",
        "",
        "INTERDICTION ABSOLUE de reutiliser ces formulations dans la nouvelle LM.",
        "Tu DOIS varier ouverture, formule familiere, transition et cloture.",
        "",
    ]
    if not formulations:
        out.append("*(Aucune formulation enregistree pour le moment - tu peux utiliser des formulations standards.)*")
        return "\n".join(out)

    out.append("| Entreprise | Ouverture | Formule familiere | Transition | Cloture |")
    out.append("|---|---|---|---|---|")
    for f in formulations:
        ent = (f.get("entreprise") or "").replace("|", "/")[:30]
        ouv = (f.get("ouverture") or "").replace("|", "/").replace("\n", " ")[:60]
        ff = (f.get("formule_familiere") or "").replace("|", "/").replace("\n", " ")[:60]
        tr = (f.get("transition") or "").replace("|", "/").replace("\n", " ")[:40]
        cl = (f.get("cloture") or "").replace("|", "/").replace("\n", " ")[:40]
        out.append(f"| {ent} | {ouv} | {ff} | {tr} | {cl} |")
    return "\n".join(out)


def _render_outils() -> str:
    return """## Outils a ta disposition

- `Read` : lire des fichiers (CV base LaTeX, profil, etc.)
- `Write` : creer un nouveau fichier (notamment le CV personnalise et le DOCX final)
- `Edit` : modifier un fichier existant (utile pour adapter le .tex)
- `Bash` : executer des commandes shell. Utilise pour :
    - copier le CV base : `cp <base.tex> <folder>/CV_*.tex`
    - compiler : `xelatex -interaction=nonstopmode -output-directory=<folder> <folder>/<file>.tex`
    - verifier le PDF : `python -c "from pypdf import PdfReader; print(len(PdfReader(...).pages))"`
    - generer le DOCX : `python -c "from docx import Document; ..."`
- `WebFetch` : recuperer le contenu d'une page web (site entreprise)
- `mcp__formulations__lookup_formulations` : voir les N dernieres formulations LM utilisees
- `mcp__formulations__record_formulation` : enregistrer les formulations utilisees dans la nouvelle LM (a appeler en fin de generation)
"""


def _render_methodologie() -> str:
    return """## Methodologie attendue (etape par etape)

1. **Lire le CV base** : `Read` sur le fichier `CV_CBouillier_base.tex` indique dans le user prompt.
2. **Explorer l'entreprise** : `WebFetch` sur la page d'accueil + une page about/recrutement si disponible. Note l'activite, les valeurs, les produits.
3. **Identifier les mots-cles ATS** de l'offre : 5 a 10 termes a injecter dans le CV.
4. **Choisir un cadre de positionnement** si declencheurs presents (ex : GTB pour automatisme/CVC).
5. **Generer le CV personnalise** :
   - Copier le .tex base dans le dossier de l'offre
   - Modifier UNIQUEMENT les sections autorisees : `\\expentry` Framatome, `\\expentry` Rabat, `\\section{COMPETENCES}`, intitule sous le nom
   - Injecter les mots-cles ATS sans inventer d'information
   - Verifier l'usage strict de `-` simple (jamais `--` ni `---`)
6. **Compiler le PDF** : `xelatex -interaction=nonstopmode` jusqu'a obtenir un PDF valide
7. **Verifier 1 page** via `pypdf` (recompiler en ajustant `\\baselinestretch` si > 1 page)
8. **Lire la banque anti-repetition** via `mcp__formulations__lookup_formulations`
9. **Rediger la lettre de motivation** :
   - Ton naturel, pas trop corporate, courte et directe
   - Verbes d'action courts : pilote, concu, anime, livre, valide
   - 1 formulation familiere, ouverture/transition/cloture varies vs banque
   - Justifie (AlignmentType.JUSTIFIED)
   - Accents complets, apostrophes typographiques, espaces insecables avant `:` et `;`
   - ZERO em dash / en dash dans le XML
10. **Generer le DOCX** via `python-docx` (executer le script via Bash)
11. **Enregistrer les formulations utilisees** via `mcp__formulations__record_formulation`
12. **Retourner le JSON final** (format ci-dessous)
"""


def _render_output_format() -> str:
    return """## Format de sortie obligatoire

Quand tout est genere et compile, ton DERNIER message doit contenir UNIQUEMENT un bloc JSON :

```json
{
  "cv_path": "<chemin absolu du PDF genere>",
  "lm_path": "<chemin absolu du DOCX genere>",
  "score_ats_estime": <int 0-100>,
  "mots_cles_injectes": ["mot1", "mot2", ...],
  "cadre_applique": "<nom du cadre ou null si generique>",
  "formulations_utilisees": {
    "ouverture": "<premiere phrase de la LM>",
    "formule_familiere": "<la formulation familiere choisie>",
    "transition": "<formule de transition notable, ou ''>",
    "cloture": "<formule de cloture choisie>"
  }
}
```

Pas de texte autour, juste le JSON. C'est ce JSON qui sera parse par l'app.
"""


# ============================================================
# Construction du system prompt complet
# ============================================================

def build_system_prompt(profile: dict, formulations: Optional[list[dict]] = None) -> str:
    """Construit le system prompt complet pour le Claude Agent SDK.

    Args:
        profile : dict charge depuis profile.yaml (config.load_profile())
        formulations : liste des dernieres formulations utilisees (db.list_recent_formulations())
    """
    if formulations is None:
        formulations = []

    nom = profile.get("identite", {}).get("nom", "le candidat")

    sections = [
        f"# Mission",
        "",
        f"Tu es l'assistant de {nom} pour generer un dossier de candidature personnalise (CV PDF + lettre de motivation DOCX) a partir d'une offre d'emploi.",
        "",
        f"## Profil candidat de {nom}",
        "",
        _render_identite(profile),
        "",
        _render_formation(profile),
        "",
        _render_experiences(profile),
        "",
        _render_interets(profile),
        "",
        _render_ambitions_cibles(profile),
        "",
        _render_cadres(profile),
        "",
        _render_regles_redaction(profile),
        "",
        _render_banque_formulations(formulations),
        "",
        _render_outils(),
        "",
        _render_methodologie(),
        "",
        _render_output_format(),
    ]
    # Filter empty sections proprement
    return "\n".join(s for s in sections if s is not None).strip() + "\n"


# ============================================================
# User prompt par offre
# ============================================================

def build_user_prompt(offre, folder: Path, cv_base_path: Path,
                      cv_tex_filename: str = "") -> str:
    """Construit le user prompt specifique a une offre.

    Args:
        offre : db.Offre (avec entreprise, intitule, description, etc.)
        folder : chemin absolu du dossier cible (Entreprises/<X>/<slug>/)
        cv_base_path : chemin absolu vers le CV LaTeX base (reference, pour info)
        cv_tex_filename : nom du fichier .tex DEJA COPIE dans le folder
                          (l'agent doit juste le modifier puis compiler)
    """
    matched = ", ".join(offre.matched_skills) if offre.matched_skills else "(aucun)"
    reasons = "; ".join(offre.reasons) if offre.reasons else "(aucune)"
    slug = _safe_company_slug(offre.entreprise)
    # Si tex_filename fourni : extraire les initiales depuis le nom (CV_<INI>_<slug>.tex)
    tex_name = cv_tex_filename or f"CV_{slug}.tex"
    pdf_name = tex_name.replace(".tex", ".pdf")
    # Le nom de la LM utilise les memes initiales que le CV
    initials = "Candidat"
    if cv_tex_filename and cv_tex_filename.startswith("CV_"):
        parts = cv_tex_filename[3:].rsplit("_", 1)
        if len(parts) == 2:
            initials = parts[0]
    lm_name = f"LM_{initials}_{slug}.docx"

    return f"""# Offre a traiter

- **Entreprise** : {offre.entreprise}
- **Intitule** : {offre.intitule}
- **Source** : {offre.source}
- **URL** : {offre.url}
- **Lieu** : {offre.location}
- **Contrat** : {offre.contract}
- **Score interne** : {offre.score}/100
- **Experience requise** : {offre.experience_min} ans
- **Mots-cles deja matches au scoring** : {matched}
- **Raisons du score** : {reasons}

## Description complete de l'offre

{offre.description or "(pas de description fournie - se baser sur l'intitule et explorer le site)"}

## Dossier de travail (cwd, DEJA cree)

`{folder}`

## Fichier CV LaTeX DEJA copie dans ce dossier

Le fichier `{tex_name}` est DEJA present dans le dossier de travail (copie du CV base).
Tu dois :
1. Le LIRE avec Read
2. Le MODIFIER avec Edit pour adapter aux mots-cles ATS de l'offre
3. Le COMPILER avec Bash : `xelatex -interaction=nonstopmode {tex_name}`
4. Verifier que le PDF cree fait 1 page (sinon ajuster baselinestretch)

## Fichiers de sortie attendus (CHEMINS EXACTS)

- CV PDF : `{folder}\\{pdf_name}`
- LM DOCX : `{folder}\\{lm_name}`

NE CHANGE PAS les noms de ces fichiers. La validation cherche exactement ces noms.

## A faire

Suis la methodologie en 12 etapes du system prompt. Termine par le JSON de sortie.
"""


def _safe_company_slug(name: str) -> str:
    """Slug court pour les noms de fichiers (sans accents/espaces)."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w]+", "", s)
    return s[:30] or "Entreprise"


# ============================================================
# Test rapide en standalone
# ============================================================

if __name__ == "__main__":
    import config
    import db

    profile = config.load_profile()
    formulations = db.list_recent_formulations(limit=5)
    sp = build_system_prompt(profile, formulations)
    print(f"System prompt : {len(sp)} caracteres, ~{len(sp)//4} tokens")
    print("--- DEBUT (1000 premiers chars) ---")
    print(sp[:1000])
    print("--- FIN (500 derniers chars) ---")
    print(sp[-500:])
