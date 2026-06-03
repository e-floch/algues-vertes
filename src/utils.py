"""
Utilitaires communs : journalisation, lecture/écriture JSON,
chargement des variables d'environnement, gestion robuste des erreurs.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

# ----------------------------------------------------------------------
# Configuration du logger commun à tous les scripts
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def get_logger(nom: str) -> logging.Logger:
    """Renvoie un logger nommé, configuré uniformément."""
    return logging.getLogger(nom)


# ----------------------------------------------------------------------
# Chargement du fichier .env (variables d'environnement locales)
# ----------------------------------------------------------------------
def charger_env(chemin_env: str | Path = ".env") -> None:
    """Charge un fichier .env simple (clé=valeur) dans os.environ.

    On préfère cette implémentation maison à la dépendance python-dotenv
    pour limiter le nombre de paquets externes.
    """
    chemin = Path(chemin_env)
    if not chemin.exists():
        return
    with chemin.open("r", encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, _, valeur = ligne.partition("=")
            cle = cle.strip()
            valeur = valeur.strip().strip('"').strip("'")
            # On n'écrase pas une variable déjà définie dans l'environnement
            os.environ.setdefault(cle, valeur)


# ----------------------------------------------------------------------
# Chemins du projet (résolution relative à la racine du dépôt)
# ----------------------------------------------------------------------
RACINE = Path(__file__).resolve().parent.parent
DOSSIER_DATA = RACINE / "data"
DOSSIER_DOCS = RACINE / "docs"
DOSSIER_DOCS_DATA = DOSSIER_DOCS / "data"
DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
DOSSIER_DOCS.mkdir(parents=True, exist_ok=True)
DOSSIER_DOCS_DATA.mkdir(parents=True, exist_ok=True)


def chemin_fichier_jour(jour: date | None = None) -> Path:
    """Renvoie le chemin du fichier JSON pour un jour donné (par défaut aujourd'hui)."""
    if jour is None:
        jour = date.today()
    return DOSSIER_DATA / f"{jour.isoformat()}.json"


# ----------------------------------------------------------------------
# Lecture / écriture JSON robuste
# ----------------------------------------------------------------------
def charger_json(chemin: Path) -> Any:
    """Charge un JSON, renvoie None en cas d'erreur (fichier absent ou corrompu)."""
    try:
        with chemin.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def enregistrer_json(chemin: Path, donnees: Any) -> None:
    """Enregistre un objet en JSON avec indentation et UTF-8."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8") as f:
        json.dump(donnees, f, indent=2, ensure_ascii=False, default=_serialiseur_defaut)


def _serialiseur_defaut(obj: Any) -> str:
    """Sérialise dates et datetimes en ISO 8601."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type non sérialisable : {type(obj)}")


# ----------------------------------------------------------------------
# Recherche du dernier fichier JSON valide pour un site/zone donné
# ----------------------------------------------------------------------
def charger_dernier_jour_disponible() -> tuple[date, dict] | None:
    """Recherche le fichier JSON le plus récent dans data/ et le renvoie.

    Utile pour récupérer les dernières données valides en cas de panne d'API.
    """
    fichiers = sorted(DOSSIER_DATA.glob("*.json"), reverse=True)
    for fichier in fichiers:
        donnees = charger_json(fichier)
        if donnees:
            try:
                jour = date.fromisoformat(fichier.stem)
                return jour, donnees
            except ValueError:
                continue
    return None


# ----------------------------------------------------------------------
# Wrapper de gestion d'erreur pour les appels API
# ----------------------------------------------------------------------
class CollecteIndisponible(Exception):
    """Exception levée quand la collecte d'une donnée est impossible
    (réseau, authentification, données manquantes...).

    Le pipeline doit la rattraper et continuer avec un statut dégradé."""
