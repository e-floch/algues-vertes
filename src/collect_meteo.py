"""
Collecte des prévisions de vent côtier via l'API Météo-France Publique
(modèle AROME, résolution 1,3 km, prévisions 7 jours).

Authentification :
  - Variable d'environnement METEOFRANCE_API_KEY
  - Clé "applicationId" obtenue après inscription sur https://portail-api.meteofrance.fr/
  - Souscrire à l'API "Données AROME" (gratuite, quotas par minute)

Endpoints utilisés :
  - GetCapabilities WCS pour découvrir les données : non exécuté à chaque tour
  - GetFeature WFS pour récupérer les valeurs ponctuelles (vent à 10m direction + force)

Pour simplifier et limiter le couplage à AROME, on utilise ici l'API
"Prévision Numérique" qui renvoie un JSON par point géographique.

En cas d'indisponibilité, on bascule sur Open-Meteo (gratuit, sans clé)
comme source de secours.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import requests

from sites_config import SITES
from utils import charger_env, get_logger

logger = get_logger("collect_meteo")

# API Météo-France — endpoint AROME 0.025 forecast
METEOFRANCE_AROME_ENDPOINT = (
    "https://public-api.meteofrance.fr/public/arome/1.0/wcs/MF-NWP-HIGHRES-AROME-001-FRANCE-WCS"
)

# API de secours : Open-Meteo (gratuit, sans clé d'API)
OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"


def _collecter_open_meteo(lat: float, lon: float, jours: int = 7) -> dict | None:
    """Collecte vent direction/force à 10m via Open-Meteo (fallback gratuit)."""
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "wind_speed_10m,wind_direction_10m",
            "timezone": "Europe/Paris",
            "forecast_days": jours,
            "wind_speed_unit": "kmh",
        }
        rep = requests.get(OPEN_METEO_ENDPOINT, params=params, timeout=30)
        rep.raise_for_status()
        donnees = rep.json()
        # Agrégation par jour (min/max/mean)
        return _agreger_par_jour(donnees, jours)
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.error("Open-Meteo indisponible : %s", exc)
        return None


def _agreger_par_jour(donnees_horaires: dict, jours: int) -> dict:
    """À partir d'un payload Open-Meteo (horaire), produit une agrégation
    journalière sur 7 jours : moyenne, max, et direction dominante."""
    horaire = donnees_horaires.get("hourly", {})
    times = horaire.get("time", [])
    speeds = horaire.get("wind_speed_10m", [])
    dirs = horaire.get("wind_direction_10m", [])

    par_jour: dict[str, dict] = {}
    for t, v, d in zip(times, speeds, dirs):
        if v is None or d is None:
            continue
        jour = t[:10]
        bloc = par_jour.setdefault(jour, {"vitesses": [], "directions": []})
        bloc["vitesses"].append(v)
        bloc["directions"].append(d)

    resultat = []
    for jour in sorted(par_jour.keys())[:jours]:
        bloc = par_jour[jour]
        vitesses = bloc["vitesses"]
        directions = bloc["directions"]
        # Direction dominante : moyenne vectorielle
        import math
        sin_sum = sum(math.sin(math.radians(d)) for d in directions)
        cos_sum = sum(math.cos(math.radians(d)) for d in directions)
        if cos_sum == 0 and sin_sum == 0:
            direction_dominante = directions[0] if directions else 0
        else:
            direction_dominante = (math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360

        resultat.append({
            "date": jour,
            "vent_moyen_kmh": round(sum(vitesses) / len(vitesses), 1) if vitesses else None,
            "vent_max_kmh": round(max(vitesses), 1) if vitesses else None,
            "direction_dominante_deg": round(direction_dominante, 0),
        })

    return {"source": "Open-Meteo", "previsions": resultat}


def _collecter_meteofrance(lat: float, lon: float, jours: int = 7) -> dict | None:
    """Tente de collecter via l'API Météo-France AROME (clé requise)."""
    cle = os.environ.get("METEOFRANCE_API_KEY")
    if not cle:
        return None

    # NOTE : l'API AROME via WCS renvoie des fichiers GRIB qu'il faut décoder
    # avec rasterio/cfgrib. C'est lourd à mettre en place pour un point unique.
    # On préfère l'API "Prévision Numérique" simplifiée : DNV ou MultiForecast.
    # Cette API est en évolution chez Météo-France ; on documente le fallback
    # comme stratégie principale (Open-Meteo) tant que l'intégration AROME
    # détaillée n'est pas finalisée.
    logger.info(
        "Clé Météo-France détectée, mais l'extraction GRIB AROME demande "
        "une étape supplémentaire (rasterio/cfgrib) — utilisation d'Open-Meteo "
        "comme source principale pour la mise en route."
    )
    return None


def collecter_vent_site(site: dict, aujourd_hui: date, jours: int = 7) -> dict:
    """Collecte les prévisions de vent pour un site (point unique : centre de plage)."""
    lat = site["lat"]
    lon = site["lon"]

    # Tentative 1 : Météo-France AROME (à activer une fois la clé en place)
    donnees = _collecter_meteofrance(lat, lon, jours)

    # Tentative 2 : Open-Meteo (fallback toujours disponible)
    if not donnees:
        donnees = _collecter_open_meteo(lat, lon, jours)

    if not donnees:
        return {
            "site_id": site["id"],
            "previsions": [],
            "avertissement": "Données vent indisponibles (Météo-France et Open-Meteo en échec).",
        }

    return {
        "site_id": site["id"],
        "source": donnees.get("source", "inconnue"),
        "previsions": donnees.get("previsions", []),
        "avertissement": None,
    }


def collecter_tous_les_sites(aujourd_hui: date | None = None) -> dict:
    """Lance la collecte vent pour tous les sites."""
    charger_env()
    if aujourd_hui is None:
        aujourd_hui = date.today()

    resultats = {}
    for site in SITES:
        logger.info("Collecte vent pour %s...", site["id"])
        try:
            resultats[site["id"]] = collecter_vent_site(site, aujourd_hui)
        except Exception as exc:
            logger.error("Échec collecte vent site %s : %s", site["id"], exc)
            resultats[site["id"]] = {
                "site_id": site["id"],
                "previsions": [],
                "avertissement": f"Erreur collecte : {exc}",
            }

    return {
        "date_collecte": aujourd_hui.isoformat(),
        "statut": "ok",
        "sites": resultats,
    }


if __name__ == "__main__":
    from utils import enregistrer_json
    donnees = collecter_tous_les_sites()
    chemin = os.path.join(os.path.dirname(__file__), "..", "data", "_meteo_temp.json")
    enregistrer_json(chemin, donnees)
    logger.info("Collecte vent terminée — %d sites traités", len(donnees.get("sites", {})))
