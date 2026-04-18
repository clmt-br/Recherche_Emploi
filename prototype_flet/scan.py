"""Orchestrateur de scan — lance les scrapers en parallele et merge les resultats.

Appele depuis le bouton "Lancer le scan" de l'UI dans un thread dedie,
pour ne pas bloquer l'interface pendant les 2-5 min que durent les scrapers.
"""
import shutil
import sys
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable

import db
import paths

OUTILS = paths.outils_dir()
MERGED = OUTILS / "merged_rapport.json"


def _python_exe() -> str:
    """Resout l'interpreteur Python pour lancer les scrapers.

    Frozen : sys.executable = le .exe lui-meme, inutilisable. On cherche un
    Python externe dans le PATH.
    Dev    : sys.executable est le bon Python.
    """
    if paths.is_frozen():
        for cmd in ("python", "python3", "py"):
            p = shutil.which(cmd)
            if p:
                return p
        return ""  # absent : le scan echouera avec message clair
    return sys.executable


def _run_scraper(script: str, progress_cb: Callable[[str], None]) -> bool:
    """Lance un scraper en subprocess. Retourne True si succes."""
    py = _python_exe()
    if not py:
        progress_cb(f"Erreur {script}: Python introuvable dans le PATH (necessaire en mode .exe)")
        return False
    progress_cb(f"Scan {script}...")
    try:
        result = subprocess.run(
            [py, script],
            cwd=OUTILS,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,  # 10 min max par scraper
        )
        if result.returncode == 0:
            progress_cb(f"OK {script}")
            return True
        else:
            progress_cb(f"Erreur {script} (code {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        progress_cb(f"Timeout {script} (> 10 min)")
        return False
    except Exception as e:
        progress_cb(f"Erreur {script}: {type(e).__name__}")
        return False


def run_full_scan(progress_cb: Callable[[str], None], done_cb: Callable[[int, list[str]], None]):
    """Execute les 3 scrapers en parallele + merge + sync DB.

    progress_cb est appelee a chaque etape (pour MAJ l'UI).
    done_cb(nb_nouvelles_offres, erreurs) est appelee a la fin.
    """
    def worker():
        scripts = ["apec_batch.py", "linkedin_batch.py", "wttj_batch.py"]
        results = {}
        threads = []
        for s in scripts:
            t = threading.Thread(
                target=lambda sc=s: results.__setitem__(sc, _run_scraper(sc, progress_cb)),
            )
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        erreurs = [s for s, ok in results.items() if not ok]

        # merge
        progress_cb("Fusion des sources...")
        merge_ok = _run_scraper("merge_sources.py", progress_cb)
        if not merge_ok:
            erreurs.append("merge_sources.py")

        # sync DB
        progress_cb("Import en base...")
        date_scrape = datetime.now().strftime("%Y-%m-%d")
        nouvelles = db.sync_from_merged_json(MERGED, date_scrape)
        progress_cb(f"Import termine : {nouvelles} nouvelles offres")
        done_cb(nouvelles, erreurs)

    threading.Thread(target=worker, daemon=True).start()
