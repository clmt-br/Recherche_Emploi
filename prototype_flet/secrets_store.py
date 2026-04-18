"""Stockage securise des secrets utilisateur via Windows Credential Manager (keyring).

Utilise pour :
    - ANTHROPIC_API_KEY (clef API du Claude Agent SDK)
    - LINKEDIN_LI_AT (cookie de session LinkedIn pour le scraper)

Ces secrets ne doivent JAMAIS apparaitre dans settings.yaml (qui reste en clair).

Usage :
    import secrets_store
    secrets_store.set_secret("anthropic_api_key", "sk-ant-...")
    key = secrets_store.get_secret("anthropic_api_key")  # None si absent
    secrets_store.delete_secret("anthropic_api_key")
    if secrets_store.has_secret("anthropic_api_key"):
        ...
"""
from typing import Optional

import keyring

SERVICE_NAME = "recherche_emploi"

# Cles canoniques utilisees dans l'app
ANTHROPIC_API_KEY = "anthropic_api_key"
LINKEDIN_LI_AT = "linkedin_li_at"


def set_secret(key: str, value: str) -> None:
    """Stocke un secret (chiffre par l'OS via Credential Manager)."""
    keyring.set_password(SERVICE_NAME, key, value)


def get_secret(key: str) -> Optional[str]:
    """Recupere un secret. Retourne None si absent ou backend indisponible."""
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except Exception:
        return None


def delete_secret(key: str) -> None:
    """Supprime un secret. Silencieux si absent."""
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except Exception:
        pass


def has_secret(key: str) -> bool:
    return bool(get_secret(key))
