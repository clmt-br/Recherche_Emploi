"""Helpers de concretisation : preparation du dossier candidature et navigation.

La generation reelle (CV+LM) est pilotee par agent_runner.run_one(),
qui delegue au Claude Agent SDK avec acces aux outils Read/Edit/Bash/WebFetch
+ outils MCP custom (banque anti-repetition).

Ce module ne contient plus que les helpers de filesystem cote prototype Flet.
"""
import re
import subprocess
import unicodedata
from pathlib import Path

import db
import paths

ROOT = paths.project_dir()
ENTREPRISES = paths.entreprises_dir()


def _slugify(text: str, max_len: int = 40) -> str:
    """Convertit un titre d'offre en slug safe pour nom de dossier."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"\s*[HFhf]/[HFhf]\s*", "", text)  # retire H/F
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:max_len].strip("_")


def prepare_folder(offre: db.Offre) -> Path:
    """Cree Entreprises/<Company>/<Titre_resume>/ et renvoie son chemin absolu."""
    company_dir = ENTREPRISES / offre.entreprise.strip()
    offer_dir = company_dir / _slugify(offre.intitule)
    offer_dir.mkdir(parents=True, exist_ok=True)
    return offer_dir


def open_folder_in_explorer(folder: Path):
    """Ouvre le dossier dans Windows Explorer."""
    subprocess.Popen(["explorer", str(folder)])
