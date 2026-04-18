"""Validators post-generation pour CV (PDF) et LM (DOCX).

Verifications appliquees apres qu'un agent Claude a genere les fichiers :
    - LaTeX a-t-il compile sans erreur fatale ?
    - PDF = 1 page exactement ?
    - Pas d'em dash / en dash dans le XML du DOCX ?
    - Accents francais presents dans les mots cles attendus ?
    - Mots-cles ATS de l'offre injectes dans le CV ?

Si un check echoue, le ValidationReport.errors est non vide -> retry intelligent
ou statut a_revoir. Le report JSON est stocke en DB pour debug.
"""
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ============================================================
# Mots francais qui DOIVENT avoir leurs accents
# (apparition sans accent = erreur de typo, hors contexte specifique)
# ============================================================
ACCENTS_MOTS_OBLIGATOIRES = [
    ("Clement", "Clément"),
    ("etudes", "études"),
    ("referentiels", "référentiels"),
    ("reunions", "réunions"),
    ("ingenieurs", "ingénieurs"),
    ("ingenieur", "ingénieur"),
    ("qualite", "qualité"),
    ("immediatement", "immédiatement"),
    ("federe", "fédéré"),
    ("concretement", "concrètement"),
    ("differents", "différents"),
    ("specialiste", "spécialiste"),
    ("La Defense", "La Défense"),
    ("mecanique", "mécanique"),
    ("mecatronique", "mécatronique"),
    ("methodes", "méthodes"),
    ("electronique", "électronique"),
    ("electrotechnique", "électrotechnique"),
    ("regulation", "régulation"),
    ("batiment", "bâtiment"),
    ("controle", "contrôle"),
    ("interesse", "intéressé"),
    ("interet", "intérêt"),
]


# ============================================================
# ValidationReport
# ============================================================

@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cv_path: str = ""
    lm_path: str = ""
    pages_pdf: int = 0
    em_dash_lines: list[str] = field(default_factory=list)
    accents_manques: list[str] = field(default_factory=list)
    ats_score: int = 0
    ats_missing_keywords: list[str] = field(default_factory=list)
    latex_log_excerpt: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Compilation LaTeX
# ============================================================

def compile_latex(tex_path: Path, output_dir: Optional[Path] = None) -> tuple[bool, str]:
    """Compile un .tex via xelatex. Retourne (ok, log_excerpt).

    output_dir : ou ecrire le PDF (defaut = meme dossier que .tex).
    En cas d'echec, le log contient les premieres lignes d'erreur LaTeX.
    """
    if not tex_path.exists():
        return False, f"Fichier .tex introuvable : {tex_path}"

    out_dir = output_dir or tex_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    if not shutil.which("xelatex"):
        return False, "xelatex introuvable dans le PATH (installer MikTeX)"

    try:
        result = subprocess.run(
            ["xelatex", "-interaction=nonstopmode",
             f"-output-directory={out_dir}", str(tex_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout xelatex (>60s)"
    except Exception as ex:
        return False, f"Erreur subprocess xelatex : {ex}"

    pdf_path = out_dir / (tex_path.stem + ".pdf")
    if pdf_path.exists() and result.returncode == 0:
        return True, ""

    # Extraire les premieres erreurs LaTeX du log
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    error_lines = []
    for line in output.splitlines():
        if line.startswith("!") or "Error" in line or "Fatal" in line:
            error_lines.append(line.strip())
            if len(error_lines) >= 5:
                break
    excerpt = "\n".join(error_lines) or output[-500:]
    return False, excerpt


# ============================================================
# Verification PDF
# ============================================================

def check_pdf_one_page(pdf_path: Path) -> tuple[bool, int]:
    """Retourne (ok=1page, nombre_de_pages)."""
    if not pdf_path.exists():
        return False, 0
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        n = len(reader.pages)
        return n == 1, n
    except Exception:
        return False, 0


# ============================================================
# Em dash / en dash detection
# ============================================================

EM_EN_DASH_RE = re.compile(r"[\u2013\u2014]")  # en dash, em dash


def check_em_dash_in_text(content: str) -> list[str]:
    """Retourne la liste des lignes contenant un em ou en dash."""
    bad = []
    for i, line in enumerate(content.splitlines(), 1):
        if EM_EN_DASH_RE.search(line):
            bad.append(f"L{i}: {line.strip()[:120]}")
    return bad


def check_em_dash_in_docx(docx_path: Path) -> list[str]:
    """Cherche les em/en dash dans le XML interne d'un DOCX (zip + word/document.xml)."""
    if not docx_path.exists():
        return [f"DOCX introuvable : {docx_path}"]
    try:
        with zipfile.ZipFile(docx_path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as ex:
        return [f"Lecture DOCX echouee : {ex}"]
    return check_em_dash_in_text(xml)


def check_em_dash_in_tex(tex_path: Path) -> list[str]:
    """Cherche les em/en dash dans un .tex (litteralement OU `--` / `---` qui les produisent)."""
    if not tex_path.exists():
        return [f".tex introuvable : {tex_path}"]
    content = tex_path.read_text(encoding="utf-8", errors="replace")
    bad = check_em_dash_in_text(content)
    # Detecter aussi `--` et `---` qui produisent en/em dash en LaTeX
    for i, line in enumerate(content.splitlines(), 1):
        # Ignorer les lignes commentees
        stripped = line.split("%", 1)[0]
        if "---" in stripped:
            bad.append(f"L{i} (---): {stripped.strip()[:120]}")
        elif re.search(r"(?<!-)--(?!-)", stripped):
            bad.append(f"L{i} (--): {stripped.strip()[:120]}")
    return bad


# ============================================================
# Accents francais obligatoires
# ============================================================

def check_accents_in_text(content: str) -> list[str]:
    """Retourne les mots qui apparaissent SANS accent alors qu'ils devraient.

    Ex: 'Clement' detecte si 'Clement' apparait sans aucun 'Clément' dans le texte.
    Tolere si le mot accentue existe aussi (faux positif typique : reference vs référence).
    """
    out = []
    for sans, avec in ACCENTS_MOTS_OBLIGATOIRES:
        # Recherche en word boundary, insensible a la casse partielle (premier char majuscule respecte)
        pattern_sans = r"\b" + re.escape(sans) + r"\b"
        if re.search(pattern_sans, content):
            # Si la version accentuee n'existe nulle part, c'est probablement une erreur
            if avec not in content:
                out.append(f"'{sans}' trouve sans accent (devrait etre '{avec}')")
    return out


def check_accents_in_docx(docx_path: Path) -> list[str]:
    if not docx_path.exists():
        return [f"DOCX introuvable : {docx_path}"]
    try:
        with zipfile.ZipFile(docx_path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as ex:
        return [f"Lecture DOCX echouee : {ex}"]
    return check_accents_in_text(xml)


# ============================================================
# Score ATS (mots-cles attendus presents dans le CV)
# ============================================================

def score_ats(content: str, expected_keywords: list[str]) -> tuple[int, list[str]]:
    """Score 0-100 + liste des mots-cles manquants.

    Score = 100 * (nb_keywords_presents / nb_keywords_attendus).
    Match insensible a la casse, normalise les accents pour la comparaison.
    """
    if not expected_keywords:
        return 100, []
    norm_content = _strip_accents(content.lower())
    missing = []
    found = 0
    for kw in expected_keywords:
        norm_kw = _strip_accents(kw.lower())
        if norm_kw in norm_content:
            found += 1
        else:
            missing.append(kw)
    score = int(100 * found / len(expected_keywords))
    return score, missing


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


# ============================================================
# Lancement de tous les validators sur un dossier offre
# ============================================================

def find_files(folder: Path) -> tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """Localise CV.tex, CV.pdf, LM.docx dans un dossier offre.

    Retourne (tex_path, pdf_path, docx_path) - chacun peut etre None si absent.
    """
    tex = next(iter(folder.glob("CV_*.tex")), None)
    pdf = next(iter(folder.glob("CV_*.pdf")), None)
    docx = next(iter(folder.glob("LM_*.docx")), None)
    return tex, pdf, docx


def run_all(folder: Path, expected_keywords: Optional[list[str]] = None) -> ValidationReport:
    """Execute tous les validators et agrege en un ValidationReport."""
    expected_keywords = expected_keywords or []
    report = ValidationReport()

    tex, pdf, docx = find_files(folder)

    # ----- Verifs CV (LaTeX + PDF) -----
    if pdf is None:
        report.errors.append(f"Aucun CV_*.pdf trouve dans {folder}")
    else:
        report.cv_path = str(pdf)
        ok, n_pages = check_pdf_one_page(pdf)
        report.pages_pdf = n_pages
        if not ok:
            report.errors.append(f"CV PDF doit etre 1 page (actuellement {n_pages})")

    if tex is not None:
        em_in_tex = check_em_dash_in_tex(tex)
        if em_in_tex:
            report.em_dash_lines.extend([f"[CV.tex] {x}" for x in em_in_tex[:10]])
            report.errors.append(f"Em/en dash detectes dans le .tex ({len(em_in_tex)} lignes)")

    # ----- Verifs LM (DOCX) -----
    if docx is None:
        report.errors.append(f"Aucun LM_*.docx trouve dans {folder}")
    else:
        report.lm_path = str(docx)
        em_in_docx = check_em_dash_in_docx(docx)
        if em_in_docx:
            report.em_dash_lines.extend([f"[LM.docx] {x}" for x in em_in_docx[:10]])
            report.errors.append(f"Em/en dash detectes dans le DOCX ({len(em_in_docx)} occurrences)")

        accents_lm = check_accents_in_docx(docx)
        if accents_lm:
            report.accents_manques.extend(accents_lm)
            report.warnings.append(f"Accents manquants dans LM ({len(accents_lm)} mots)")

    # ----- Score ATS sur le .tex (texte brut) -----
    if tex is not None and expected_keywords:
        tex_content = tex.read_text(encoding="utf-8", errors="replace")
        score, missing = score_ats(tex_content, expected_keywords)
        report.ats_score = score
        report.ats_missing_keywords = missing
        if score < 60:
            report.errors.append(f"Score ATS trop bas ({score}/100), {len(missing)} mots-cles manquants")
        elif score < 80:
            report.warnings.append(f"Score ATS moyen ({score}/100)")

    # ----- Verdict global -----
    report.ok = len(report.errors) == 0
    return report


# ============================================================
# Helper : description courte pour retry intelligent
# ============================================================

def format_errors_for_retry(report: ValidationReport) -> str:
    """Formatte les erreurs pour les re-injecter dans un prompt de retry."""
    if report.ok:
        return ""
    parts = ["La generation precedente a echoue aux verifications suivantes :", ""]
    for err in report.errors:
        parts.append(f"- {err}")
    if report.em_dash_lines:
        parts.append("\nLignes contenant em/en dash a corriger (utiliser - simple ou virgule) :")
        for line in report.em_dash_lines[:5]:
            parts.append(f"  {line}")
    if report.accents_manques:
        parts.append("\nMots francais sans accent a corriger :")
        for w in report.accents_manques[:5]:
            parts.append(f"  - {w}")
    if report.ats_missing_keywords:
        parts.append(f"\nMots-cles ATS a injecter dans le CV : {', '.join(report.ats_missing_keywords[:8])}")
    parts.append("\nCorrige et relance la compilation. Termine par le JSON de sortie.")
    return "\n".join(parts)


# ============================================================
# Smoke test
# ============================================================

if __name__ == "__main__":
    # Test em dash
    bad = check_em_dash_in_text("Ligne propre.\nLigne avec em — dash.\nAutre ligne.")
    print(f"Em dash detection : {len(bad)} lignes")
    for b in bad:
        print(f"  {b}")

    # Test accents
    miss = check_accents_in_text("Bonjour Clement, je suis ingenieur en mecanique.")
    print(f"\nAccents manquants : {len(miss)}")
    for m in miss:
        print(f"  {m}")

    # Test ATS
    score, missing = score_ats(
        "Le candidat maitrise CATIA V5 et la cotation ISO GPS.",
        ["catia", "iso gps", "python", "asn"],
    )
    print(f"\nATS score : {score}/100, manquants : {missing}")

    # Test sur un dossier existant si dispo
    sample_folder = Path(__file__).parent.parent / "Entreprises"
    if sample_folder.exists():
        for sub in sample_folder.iterdir():
            if sub.is_dir():
                tex, pdf, docx = find_files(sub)
                if pdf or docx:
                    print(f"\n--- {sub.name} ---")
                    r = run_all(sub, expected_keywords=["catia", "iso gps", "framatome"])
                    print(f"  OK={r.ok} pages={r.pages_pdf} ats={r.ats_score}")
                    print(f"  errors={r.errors[:3]}")
                    print(f"  warnings={r.warnings[:3]}")
                    break
