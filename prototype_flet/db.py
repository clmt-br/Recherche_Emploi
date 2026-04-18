"""Couche SQLite — une base unique candidatures.db qui remplace les 4 tableaux Notion.

Schema etendu avec tous les champs produits par les scrapers
(apec_batch.py, linkedin_batch.py, wttj_batch.py) via merge_sources.py.

Schema v3 ajoute :
- Colonnes offres : cv_path, lm_path, last_error, validation_report, concretize_attempts
- Statut a_revoir (validation post-generation echouee 2 fois)
- Table app_meta (key/value) pour metadata applicatives
- Table formulations_utilisees pour banque anti-repetition LM
"""
import sqlite3
import json
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import paths

DB_PATH = paths.db_path()
SCHEMA_VERSION = 3


@dataclass
class Offre:
    id: int
    job_id: Optional[str]
    source: str
    entreprise: str
    intitule: str
    url: str
    location: str
    contract: str
    description: str
    score: int
    verdict: str
    experience_min: float
    listed_date: str
    date_scrape: str
    statut: str
    reasons: list = field(default_factory=list)
    matched_skills: list = field(default_factory=list)
    dossier_pc: str = ""
    date_envoi: Optional[str] = None
    date_relance: Optional[str] = None
    # Schema v3
    cv_path: str = ""
    lm_path: str = ""
    last_error: str = ""
    validation_report: dict = field(default_factory=dict)
    concretize_attempts: int = 0

    @classmethod
    def from_row(cls, row) -> "Offre":
        d = dict(row)
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["matched_skills"] = json.loads(d.get("matched_skills") or "[]")
        vr = d.get("validation_report")
        d["validation_report"] = json.loads(vr) if vr else {}
        # Defaults pour None (colonnes nullable)
        for k, default in [
            ("cv_path", ""), ("lm_path", ""), ("last_error", ""),
            ("dossier_pc", ""), ("concretize_attempts", 0),
        ]:
            if d.get(k) is None:
                d[k] = default
        # Filtrer les colonnes inconnues (forward compat)
        valid = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in valid}
        return cls(**d)


def _connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _connect()
    con.execute("""
        CREATE TABLE IF NOT EXISTS offres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE,
            source TEXT NOT NULL,
            entreprise TEXT NOT NULL,
            intitule TEXT NOT NULL,
            url TEXT,
            location TEXT DEFAULT '',
            contract TEXT DEFAULT '',
            description TEXT DEFAULT '',
            score INTEGER NOT NULL DEFAULT 0,
            verdict TEXT DEFAULT '',
            experience_min REAL DEFAULT 0,
            listed_date TEXT DEFAULT '',
            date_scrape TEXT NOT NULL,
            statut TEXT NOT NULL DEFAULT 'rapport',
            reasons TEXT DEFAULT '[]',
            matched_skills TEXT DEFAULT '[]',
            dossier_pc TEXT DEFAULT '',
            date_envoi TEXT,
            date_relance TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_statut ON offres(statut)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_score ON offres(score DESC)")
    con.commit()

    _migrate(con)

    # Seed si vide
    count = con.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
    if count == 0:
        _seed_from_merged_json_or_demo(con)
    con.close()


def _migrate(con):
    """Migration douce idempotente vers SCHEMA_VERSION courante.

    Cree app_meta + formulations_utilisees si absentes, ajoute les colonnes
    manquantes a offres, et marque la version. Sauvegarde la DB existante
    une seule fois avant la premiere bascule v2 -> v3.
    """
    # 1. app_meta (porte la version)
    con.execute("""
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    con.commit()

    current = con.execute(
        "SELECT value FROM app_meta WHERE key = 'schema_version'"
    ).fetchone()
    current_v = int(current["value"]) if current else 0

    if current_v >= SCHEMA_VERSION:
        return

    # Backup une fois avant migration
    if DB_PATH.exists() and current_v > 0:
        backup = DB_PATH.with_suffix(f".db.bak.v{current_v}")
        if not backup.exists():
            try:
                shutil.copy2(DB_PATH, backup)
            except Exception:
                pass  # backup best-effort

    # 2. Ajouter colonnes manquantes a offres
    cols = {r["name"] for r in con.execute("PRAGMA table_info(offres)").fetchall()}
    new_cols = [
        ("cv_path", "TEXT DEFAULT ''"),
        ("lm_path", "TEXT DEFAULT ''"),
        ("last_error", "TEXT DEFAULT ''"),
        ("validation_report", "TEXT DEFAULT ''"),
        ("concretize_attempts", "INTEGER DEFAULT 0"),
    ]
    for name, defn in new_cols:
        if name not in cols:
            con.execute(f"ALTER TABLE offres ADD COLUMN {name} {defn}")

    # 3. Table formulations_utilisees
    con.execute("""
        CREATE TABLE IF NOT EXISTS formulations_utilisees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            entreprise TEXT,
            ouverture TEXT DEFAULT '',
            formule_familiere TEXT DEFAULT '',
            transition TEXT DEFAULT '',
            cloture TEXT DEFAULT '',
            date_generation TEXT NOT NULL
        )
    """)
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_formulations_date "
        "ON formulations_utilisees(date_generation DESC)"
    )

    # 4. Marquer la version
    con.execute(
        "INSERT OR REPLACE INTO app_meta(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    con.commit()


def _seed_from_merged_json_or_demo(con):
    """Premier lancement : essaie de charger merged_rapport.json si present.

    Sinon, ne fait RIEN (table vide). L'utilisateur lance le scan via le
    bouton dans l'UI pour peupler le rapport.
    """
    merged = paths.outils_dir() / "merged_rapport.json"
    if merged.exists():
        try:
            data = json.loads(merged.read_text(encoding="utf-8"))
            for o in data:
                if o.get("verdict") != "A_POSTULER":
                    continue
                con.execute("""
                    INSERT OR IGNORE INTO offres
                    (job_id, source, entreprise, intitule, url, location, contract,
                     description, score, verdict, experience_min, listed_date,
                     date_scrape, statut, reasons, matched_skills)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rapport', ?, ?)
                """, (
                    o.get("job_id"), o.get("source", ""), o.get("company", ""),
                    o.get("title", ""), o.get("url", ""), o.get("location", ""),
                    o.get("contract", ""), o.get("description", ""),
                    o.get("score", 0), o.get("verdict", ""),
                    o.get("experience_min", 0), o.get("listed_date", ""),
                    datetime.now().strftime("%Y-%m-%d"),
                    json.dumps(o.get("reasons", []), ensure_ascii=False),
                    json.dumps(o.get("matched_skills", []), ensure_ascii=False),
                ))
            con.commit()
        except Exception:
            pass


def list_offres(statut: Optional[str] = None) -> list[Offre]:
    con = _connect()
    if statut:
        rows = con.execute(
            "SELECT * FROM offres WHERE statut = ? ORDER BY score DESC, date_scrape DESC",
            (statut,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM offres ORDER BY score DESC, date_scrape DESC"
        ).fetchall()
    con.close()
    return [Offre.from_row(r) for r in rows]


def get_offre(offre_id: int) -> Optional[Offre]:
    con = _connect()
    row = con.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
    con.close()
    return Offre.from_row(row) if row else None


def update_statut(offre_id: int, statut: str):
    con = _connect()
    con.execute("UPDATE offres SET statut = ? WHERE id = ?", (statut, offre_id))
    con.commit()
    con.close()


def mark_envoyee(offre_id: int, date_envoi: str, date_relance: str):
    con = _connect()
    con.execute(
        "UPDATE offres SET statut = 'envoyee', date_envoi = ?, date_relance = ? WHERE id = ?",
        (date_envoi, date_relance, offre_id),
    )
    con.commit()
    con.close()


def set_dossier_pc(offre_id: int, dossier: str):
    con = _connect()
    con.execute("UPDATE offres SET dossier_pc = ? WHERE id = ?", (dossier, offre_id))
    con.commit()
    con.close()


def update_concretize_progress(
    offre_id: int,
    *,
    cv_path: Optional[str] = None,
    lm_path: Optional[str] = None,
    last_error: Optional[str] = None,
    validation_report: Optional[dict] = None,
    attempts_increment: bool = False,
    new_statut: Optional[str] = None,
):
    """Met a jour les champs lies a la concretisation, en un seul UPDATE."""
    sets, args = [], []
    if cv_path is not None:
        sets.append("cv_path = ?"); args.append(cv_path)
    if lm_path is not None:
        sets.append("lm_path = ?"); args.append(lm_path)
    if last_error is not None:
        sets.append("last_error = ?"); args.append(last_error)
    if validation_report is not None:
        sets.append("validation_report = ?")
        args.append(json.dumps(validation_report, ensure_ascii=False))
    if attempts_increment:
        sets.append("concretize_attempts = concretize_attempts + 1")
    if new_statut is not None:
        sets.append("statut = ?"); args.append(new_statut)
    if not sets:
        return
    args.append(offre_id)
    con = _connect()
    con.execute(f"UPDATE offres SET {', '.join(sets)} WHERE id = ?", args)
    con.commit()
    con.close()


def sync_from_merged_json(json_path: Path, date_scrape: str) -> int:
    """Importe les offres d'un merged_rapport.json vers la DB. Retourne le nb de nouvelles."""
    if not json_path.exists():
        return 0
    data = json.loads(json_path.read_text(encoding="utf-8"))
    con = _connect()
    before = con.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
    for o in data:
        if o.get("verdict") != "A_POSTULER":
            continue
        con.execute("""
            INSERT OR IGNORE INTO offres
            (job_id, source, entreprise, intitule, url, location, contract,
             description, score, verdict, experience_min, listed_date,
             date_scrape, statut, reasons, matched_skills)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rapport', ?, ?)
        """, (
            o.get("job_id"), o.get("source", ""), o.get("company", ""),
            o.get("title", ""), o.get("url", ""), o.get("location", ""),
            o.get("contract", ""), o.get("description", ""),
            o.get("score", 0), o.get("verdict", ""),
            o.get("experience_min", 0), o.get("listed_date", ""),
            date_scrape,
            json.dumps(o.get("reasons", []), ensure_ascii=False),
            json.dumps(o.get("matched_skills", []), ensure_ascii=False),
        ))
    con.commit()
    after = con.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
    con.close()
    return after - before


def insert_offre(entreprise: str, intitule: str, source: str, score: int,
                 url: str, date_scrape: str, statut: str = "rapport"):
    """Insertion minimale (utilise pour les tests / ajouts manuels)."""
    con = _connect()
    con.execute("""
        INSERT INTO offres(source, entreprise, intitule, url, score, date_scrape, statut)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (source, entreprise, intitule, url, score, date_scrape, statut))
    con.commit()
    con.close()


# ============================================================
# Helpers app_meta (key/value applicatif)
# ============================================================

def get_meta(key: str) -> Optional[str]:
    con = _connect()
    row = con.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    con.close()
    return row["value"] if row else None


def set_meta(key: str, value: str):
    con = _connect()
    con.execute(
        "INSERT OR REPLACE INTO app_meta(key, value) VALUES (?, ?)",
        (key, value),
    )
    con.commit()
    con.close()


# ============================================================
# Helpers formulations_utilisees (banque anti-repetition LM)
# ============================================================

def record_formulation(
    job_id: str,
    entreprise: str,
    ouverture: str = "",
    formule_familiere: str = "",
    transition: str = "",
    cloture: str = "",
):
    con = _connect()
    con.execute("""
        INSERT INTO formulations_utilisees
        (job_id, entreprise, ouverture, formule_familiere, transition, cloture, date_generation)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        job_id, entreprise, ouverture, formule_familiere, transition, cloture,
        datetime.now().isoformat(timespec="seconds"),
    ))
    con.commit()
    con.close()


def list_recent_formulations(limit: int = 30) -> list[dict]:
    """Retourne les N dernieres formulations utilisees, plus recentes en premier."""
    con = _connect()
    rows = con.execute(
        """SELECT entreprise, ouverture, formule_familiere, transition, cloture, date_generation
           FROM formulations_utilisees
           ORDER BY date_generation DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def cleanup_dead_agents() -> int:
    """Au demarrage, marque comme a_revoir les offres avec un agent interrompu
    (concretize_attempts > 0 mais cv_path vide). Cela arrive si l'app a ete
    fermee pendant une concretisation. Retourne le nb d'offres affectees.
    """
    con = _connect()
    rows = con.execute(
        "SELECT id FROM offres "
        "WHERE statut IN ('en_cours', 'rapport') "
        "AND concretize_attempts > 0 "
        "AND (cv_path IS NULL OR cv_path = '')"
    ).fetchall()
    n = len(rows)
    if n > 0:
        con.execute(
            "UPDATE offres SET statut = 'a_revoir', "
            "last_error = 'Concretisation interrompue (app fermee). Re-tenter.' "
            "WHERE statut IN ('en_cours', 'rapport') "
            "AND concretize_attempts > 0 "
            "AND (cv_path IS NULL OR cv_path = '')"
        )
        con.commit()
    con.close()
    return n
