"""Resolution des chemins de l'app (compatible dev + .exe PyInstaller).

PyInstaller --onefile extrait les fichiers internes dans un dossier temporaire
(_MEIxxxxx) et y pointe `__file__`. Si on stocke la DB ou profile.yaml dans
ce dossier, ils sont PERDUS a chaque lancement.

Solution : detecter `sys.frozen` et utiliser le dossier du .exe pour les
donnees utilisateur, sinon le dossier prototype_flet/ comme avant.

Structures :
    Dev  : Recherche Travail/prototype_flet/{app.py, db.py, candidatures.db,
                                              profile.yaml, settings.yaml}
           Recherche Travail/{CV_template.tex, Entreprises/}
    Exe  : <dossier_exe>/{RechercheEmploi.exe, candidatures.db, profile.yaml,
                          settings.yaml, CV_template.tex, Entreprises/}
"""
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True si on tourne dans un .exe PyInstaller (--onefile ou --onedir)."""
    return getattr(sys, "frozen", False)


def app_dir() -> Path:
    """Dossier ou stocker les donnees utilisateur (DB, profile, settings).

    Frozen : a cote du .exe.
    Dev    : dossier prototype_flet/.
    """
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent


def project_dir() -> Path:
    """Dossier projet contenant CV_template.tex et Entreprises/.

    Frozen : meme dossier que le .exe (bundle self-contained).
    Dev    : parent de prototype_flet/ (la racine projet).
    """
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def db_path() -> Path:
    return app_dir() / "candidatures.db"


def profile_path() -> Path:
    return app_dir() / "profile.yaml"


def settings_path() -> Path:
    return app_dir() / "settings.yaml"


def entreprises_dir() -> Path:
    return project_dir() / "Entreprises"


def outils_dir() -> Path:
    """Dossier des scrapers (apec_batch, linkedin_batch, wttj_batch).

    Frozen : 'OUTILS' a cote du .exe.
    Dev    : 'OUTILS' a la racine projet.
    """
    return project_dir() / "OUTILS"
