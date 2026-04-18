"""Profil candidat et parametres du scan — stockes en YAML a cote de app.py.

Ces fichiers sont lus par les scrapers et par les prompts Claude Code.
Un nouvel utilisateur change juste profile.yaml et l'app s'adapte.

Schema profile.yaml (hierarchique) :
- identite, formation, experiences, interets_complementaires,
  profil_ambitions, cibles, cadres_positionnement, regles_redaction
"""
import yaml
from pathlib import Path

import paths

PROFILE_PATH = paths.profile_path()
SETTINGS_PATH = paths.settings_path()


# ============================================================
# Profil VIDE par defaut. L'utilisateur remplit dans l'onglet Profil
# et profile.yaml est ecrit a cote de l'app.
# ============================================================
DEFAULT_PROFILE = {
    "identite": {
        "nom": "",
        "email": "",
        "telephone": "",
        "localisation": "",
        "mobilite": "",
        "disponibilite": "",
    },
    "formation": {
        "ecole": "",
        "cursus": "",
        "prepa": "",
        "international": "",
        "specialite": "",
        "contenu_cursus": "",
    },
    "experiences": [],
    "interets_complementaires": [],
    "profil_ambitions": {
        "cible_prioritaire_taille": "",
        "raison_cible": "",
        "ouverture_postes": [],
        "contexte_depart": "",
        "esn_presta": "",
    },
    "cibles": {
        "postes_a_conserver": [],
        "exclusions_strictes": [],
        "exception_intitule_commercial": "",
        "zone_prioritaire": "",
        "zone_acceptable": "",
    },
    "cadres_positionnement": [],
    "regles_redaction": {
        "ne_jamais_dire": [],
        "vocabulaire_specifique": [],
        "tirets_long_interdits": True,
        "accents_obligatoires": True,
    },
}


DEFAULT_SETTINGS = {
    "scan_heure": "09:05",
    "scan_jours": "Lundi-Vendredi",
    "score_minimum_draft": 80,
    "mots_cles": "",
    "departements_idf": "75, 92, 93, 94, 95, 78, 91, 77",
    "rayon_km": 50,
    "sources_actives": "APEC, LinkedIn, WTTJ",
}


def load_profile() -> dict:
    if PROFILE_PATH.exists():
        data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
        if data and isinstance(data, dict) and "identite" in data:
            return data
    return DEFAULT_PROFILE.copy()


def save_profile(data: dict):
    PROFILE_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        data = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if data else DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()


def save_settings(data: dict):
    SETTINGS_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# ---- Helpers pour les listes ----

def empty_experience() -> dict:
    return {
        "entreprise": "", "lieu": "", "periode": "",
        "type_contrat": "", "niveau_mise_en_avant": "mentionner",
        "mission": "", "methodologie": "",
        "competences": [], "referentiels": [],
        "contexte": "", "notes": "",
    }


def empty_interet() -> dict:
    return {
        "titre": "", "description": "",
        "competences": [], "pertinent_si": "",
    }


def empty_cadre() -> dict:
    return {
        "nom": "", "declencheurs": [],
        "motivation": "",
        "acquis_theoriques": [], "acquis_pratiques": [],
        "regles_strictes": [],
    }
