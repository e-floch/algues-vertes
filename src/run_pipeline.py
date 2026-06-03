"""
Orchestration du pipeline complet : collecte des données, calcul du risque,
génération du tableau de bord.

Lancement local :
    python src/run_pipeline.py

Lancement par GitHub Actions : voir .github/workflows/daily_update.yml
"""
from __future__ import annotations

import sys
from datetime import date

import collect_airbreizh
import collect_maree
import collect_meteo
import collect_sentinel
import compute_risk
import generate_dashboard
from utils import (
    chemin_fichier_jour,
    enregistrer_json,
    get_logger,
)

logger = get_logger("run_pipeline")


def lancer_pipeline(jour: date | None = None) -> dict:
    """Lance le pipeline complet pour une date donnée (par défaut : aujourd'hui)."""
    if jour is None:
        jour = date.today()
    logger.info("=== Lancement du pipeline pour le %s ===", jour.isoformat())

    # 1. Sentinel-2 (peut échouer sans bloquer)
    try:
        donnees_sentinel = collect_sentinel.collecter_tous_les_sites(jour)
    except Exception as exc:
        logger.error("Sentinel-2 — échec critique : %s", exc)
        donnees_sentinel = {
            "date_collecte": jour.isoformat(),
            "statut": "indisponible",
            "raison": str(exc),
            "sites": {},
        }

    # 2. Météo (vent)
    try:
        donnees_meteo = collect_meteo.collecter_tous_les_sites(jour)
    except Exception as exc:
        logger.error("Météo — échec critique : %s", exc)
        donnees_meteo = {"date_collecte": jour.isoformat(), "statut": "indisponible", "sites": {}}

    # 3. Marées
    try:
        donnees_maree = collect_maree.collecter_tous_les_sites(jour)
    except Exception as exc:
        logger.error("Marées — échec critique : %s", exc)
        donnees_maree = {"date_collecte": jour.isoformat(), "statut": "indisponible", "sites": {}}

    # 4. AirBreizh (H2S) — indicateur complémentaire, n'entre PAS dans le score
    try:
        donnees_airbreizh = collect_airbreizh.collecter_tous_les_sites(jour)
    except Exception as exc:
        logger.error("AirBreizh — échec critique : %s", exc)
        donnees_airbreizh = {"date_collecte": jour.isoformat(), "statut": "indisponible", "sites": {}}

    # 5. Calcul du risque + construction de l'état du jour
    etat = compute_risk.construire_etat_du_jour(
        donnees_sentinel,
        donnees_meteo,
        donnees_maree,
        jour,
        donnees_airbreizh=donnees_airbreizh,
    )

    # 5. Sauvegarde du fichier YYYY-MM-DD.json
    chemin = chemin_fichier_jour(jour)
    enregistrer_json(chemin, etat)
    logger.info("Données du jour sauvegardées : %s", chemin)

    # 6. Génération du tableau de bord
    res = generate_dashboard.generer_dashboard_complet()
    logger.info("Tableau de bord régénéré : %s (%d dates)", res["html"], res["dates_disponibles"])

    return etat


if __name__ == "__main__":
    # Argument optionnel : date au format YYYY-MM-DD (utile pour rejouer un jour passé)
    jour = None
    if len(sys.argv) > 1:
        try:
            jour = date.fromisoformat(sys.argv[1])
        except ValueError:
            logger.error("Date invalide : %s — usage : python run_pipeline.py [YYYY-MM-DD]", sys.argv[1])
            sys.exit(1)
    lancer_pipeline(jour)
