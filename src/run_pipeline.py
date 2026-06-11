"""
Orchestration du pipeline complet : collecte des données, calcul du risque,
génération du tableau de bord.

Lancement local :
    python src/run_pipeline.py

Lancement par GitHub Actions : voir .github/workflows/daily_update.yml
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

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

# Sentinel-2 repasse sur la Bretagne tous les ~5 jours (S2A + S2B).
# Inutile d'appeler l'API Statistics chaque jour : on réutilise les données
# existantes si la dernière image connue date de moins de SENTINEL_CACHE_JOURS.
SENTINEL_CACHE_JOURS = 14


def _recuperer_sentinel_cache(jour: date) -> dict | None:
    """Cherche dans les N derniers jours un résultat Sentinel-2 valide
    (statut ok, image_la_plus_recente non nulle et datant de moins de
    SENTINEL_CACHE_JOURS).  Renvoie les données ou None si aucun cache valide."""
    data_dir = Path(__file__).parent.parent / "data"
    for delta in range(1, SENTINEL_CACHE_JOURS + 1):
        chemin = data_dir / f"{(jour - timedelta(days=delta)).isoformat()}.json"
        if not chemin.exists():
            continue
        try:
            etat = json.loads(chemin.read_text(encoding="utf-8"))
        except Exception:
            continue

        # Récupérer la date de la dernière image via le premier site
        sites = etat.get("sites", [])
        if not sites:
            continue
        site0 = sites[0] if isinstance(sites, list) else next(iter(sites.values()), {})
        img_date_str = site0.get("sentinel", {}).get("image_la_plus_recente")
        if not img_date_str:
            continue
        try:
            img_date = date.fromisoformat(img_date_str)
        except ValueError:
            continue

        anciennete = (jour - img_date).days
        if anciennete < SENTINEL_CACHE_JOURS:
            logger.info(
                "Sentinel-2 : image du %s encore valide (%d j) — API ignorée pour économiser les PU",
                img_date_str, anciennete,
            )
            # Reconstituer une structure sentinel compatible depuis les sites en cache
            sites_sentinel = {}
            for s in (sites if isinstance(sites, list) else sites.values()):
                sid = s.get("id") or s.get("site_id")
                if sid and s.get("sentinel"):
                    sent_out = s["sentinel"]
                    # Le JSON de sortie utilise des clés courtes (ndvi_zone_0, fai_zone_2).
                    # compute_risk.py attend les clés d'origine de collect_sentinel
                    # (ndvi_zone_0_estran, ndvi_zone_1_cotier, fai_zone_2_pelagique).
                    # On les restitue ici pour que les scores soient bien calculés.
                    sent = {
                        "ndvi_zone_0_estran":   sent_out.get("ndvi_zone_0"),
                        "ndvi_zone_1_cotier":   sent_out.get("ndvi_zone_1"),
                        "fai_zone_2_pelagique": sent_out.get("fai_zone_2"),
                        "image_la_plus_recente": sent_out.get("image_la_plus_recente"),
                        # Les deux miniatures sont retéléchargées à chaque run pour
                        # rester à jour avec l'evalscript courant.
                        "image_miniature":           None,  # zone côtière (~6 km, NDVI)
                        "image_miniature_pelagique": None,  # zone pélagique (~30 km, FAI)
                        "avertissement":         sent_out.get("avertissement"),
                        "_depuis_cache":         True,
                    }
                    sites_sentinel[sid] = sent
            return {
                "date_collecte": (jour - timedelta(days=delta)).isoformat(),
                "statut": "ok",
                "raison": f"Cache réutilisé (image du {img_date_str}, {anciennete}j)",
                "sites": sites_sentinel,
            }
    return None


def lancer_pipeline(jour: date | None = None) -> dict:
    """Lance le pipeline complet pour une date donnée (par défaut : aujourd'hui)."""
    if jour is None:
        jour = date.today()
    logger.info("=== Lancement du pipeline pour le %s ===", jour.isoformat())

    # 1. Sentinel-2 — réutilise le cache si l'image a moins de SENTINEL_CACHE_JOURS
    try:
        donnees_sentinel = _recuperer_sentinel_cache(jour)
        if donnees_sentinel is None:
            logger.info("Sentinel-2 : pas de cache valide — appel API CDSE")
            donnees_sentinel = collect_sentinel.collecter_tous_les_sites(jour)
        else:
            # En mode cache, les statistiques (NDVI/FAI) sont réutilisées mais
            # les miniatures sont retéléchargées (~2 PU/site) pour rester à jour
            # avec l'evalscript courant (couleurs naturelles + vert pour les algues).
            logger.info("Sentinel-2 : retéléchargement des miniatures (cache stats)")
            miniatures = collect_sentinel.telecharger_miniatures(jour)
            # miniatures = {site_id: {"cotier": chemin|None, "pelagique": chemin|None}}
            for sid, chemins in miniatures.items():
                if sid in donnees_sentinel.get("sites", {}):
                    donnees_sentinel["sites"][sid]["image_miniature"] = chemins.get("cotier")
                    donnees_sentinel["sites"][sid]["image_miniature_pelagique"] = chemins.get("pelagique")
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
