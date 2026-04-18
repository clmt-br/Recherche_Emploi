"""Generation d'un fichier .ics pour la relance Google Calendar J+15.

Solution sans API Google : on genere un .ics que l'utilisateur peut
double-cliquer pour l'importer dans Calendar (ou qu'il glisse dans Gmail).
"""
import uuid
from pathlib import Path
from datetime import datetime, timedelta

import config
import db


def _candidate_name() -> str:
    """Recupere le nom du candidat depuis profile.yaml."""
    try:
        profile = config.load_profile()
        nom = (profile.get("identite", {}) or {}).get("nom", "").strip()
        return nom or "[ton nom]"
    except Exception:
        return "[ton nom]"


def build_ics(offre: db.Offre, date_envoi: datetime) -> str:
    """Construit le contenu texte d'un .ics pour la relance a J+15 a 14h."""
    relance = (date_envoi + timedelta(days=15)).replace(hour=14, minute=0, second=0, microsecond=0)
    end = relance + timedelta(minutes=30)

    uid = uuid.uuid4().hex + "@recherche-emploi"
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    nom = _candidate_name()

    summary = f"Relance - {offre.intitule} - {offre.entreprise}"
    description = (
        f"Objet : Relance - Candidature {offre.intitule} - {nom}\\n\\n"
        f"Bonjour,\\n\\n"
        f"Je reviens vers vous concernant ma candidature "
        f"au poste de {offre.intitule} envoyee le {date_envoi:%d/%m/%Y}.\\n\\n"
        f"Restant a votre disposition pour un echange.\\n\\n"
        f"Bien cordialement,\\n"
        f"{nom}"
    )

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//RechercheEmploi//FR\r\n"
        "CALSCALE:GREGORIAN\r\n"
        "METHOD:PUBLISH\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{relance:%Y%m%dT%H%M%S}\r\n"
        f"DTEND:{end:%Y%m%dT%H%M%S}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"DESCRIPTION:{description}\r\n"
        "BEGIN:VALARM\r\n"
        "ACTION:DISPLAY\r\n"
        "DESCRIPTION:Relance candidature\r\n"
        "TRIGGER:-PT1H\r\n"
        "END:VALARM\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def save_ics(offre: db.Offre, folder: Path, date_envoi: datetime) -> Path:
    """Ecrit le .ics dans le dossier candidature et renvoie son chemin."""
    ics = build_ics(offre, date_envoi)
    path = folder / f"relance_{offre.entreprise.replace(' ', '_')}.ics"
    path.write_text(ics, encoding="utf-8")
    return path
