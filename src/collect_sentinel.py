"""
Collecte et traitement des images Sentinel-2 via le Copernicus Data Space Ecosystem (CDSE).

Pour chaque site et chaque zone (0 = estran, 1 = côtier, 2 = pélagique), on calcule
des statistiques d'indice (NDVI, NDWI, FAI) à partir de la dernière image L2A
disponible dont la couverture nuageuse est inférieure à 80 % sur la zone.

Authentification :
  - Variables d'environnement CDSE_CLIENT_ID et CDSE_CLIENT_SECRET (OAuth2 client credentials)
    obtenues via https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings

API utilisée :
  - Sentinel Hub Process API (CDSE) : https://sh.dataspace.copernicus.eu/api/v1/process
    Permet de récupérer un indice (NDVI, FAI...) calculé côté serveur sur une bbox
    et de récupérer une statistique agrégée (moyenne, max, % de pixels > seuil).

En cas d'indisponibilité (clés absentes, réseau, etc.), la fonction renvoie None
et le pipeline continue avec une indication "Sentinel-2 indisponible".
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from sites_config import SITES, get_zones
from utils import (
    CollecteIndisponible,
    charger_env,
    enregistrer_json,
    get_logger,
)

logger = get_logger("collect_sentinel")

# Endpoints CDSE
CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
CDSE_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Seuil de couverture nuageuse au-delà duquel on remonte en arrière dans le temps
COUVERTURE_NUAGEUSE_MAX = 80.0

# Nombre de jours à remonter pour trouver une image valide
FENETRE_RECHERCHE_JOURS = 14


def _recuperer_token_oauth() -> str | None:
    """Renvoie un token OAuth2 valide, ou None si l'authentification échoue."""
    client_id = os.environ.get("CDSE_CLIENT_ID")
    client_secret = os.environ.get("CDSE_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.warning(
            "Clés CDSE_CLIENT_ID / CDSE_CLIENT_SECRET absentes — "
            "collecte Sentinel-2 désactivée."
        )
        return None

    try:
        reponse = requests.post(
            CDSE_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=20,
        )
        reponse.raise_for_status()
        return reponse.json()["access_token"]
    except (requests.RequestException, KeyError) as exc:
        logger.error("Échec de l'authentification CDSE : %s", exc)
        return None


# ----------------------------------------------------------------------
# Evalscripts — code JavaScript exécuté côté serveur Sentinel Hub
# ----------------------------------------------------------------------
# NDVI = (B08 - B04) / (B08 + B04) — végétation/algues vertes sur estran
EVALSCRIPT_NDVI = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL"] }],
    output: [
      { id: "default", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  // SCL : 8 = nuage moyenne probabilité, 9 = nuage forte probabilité, 10 = cirrus
  if (s.SCL === 8 || s.SCL === 9 || s.SCL === 10 || s.SCL === 3) {
    return { default: [NaN], dataMask: [0] };
  }
  let denom = s.B08 + s.B04;
  let ndvi = (denom === 0) ? 0 : (s.B08 - s.B04) / denom;
  return { default: [ndvi], dataMask: [1] };
}
"""

# FAI = B08 - (B04 + (B11 - B04) * (842 - 665) / (1610 - 665))
# Indice de masses algales flottantes (Hu, 2009) — utilisé en zone pélagique
EVALSCRIPT_FAI = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "B11", "SCL"] }],
    output: [
      { id: "default", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  // SCL 6 = eau — on ne calcule le FAI que sur les pixels eau pour éviter
  // que la végétation terrestre (NIR élevé) gonfle artificiellement le score.
  // Nuages et ombres également exclus (3 = ombre, 8/9/10 = nuages/cirrus).
  if (s.SCL !== 6) {
    return { default: [NaN], dataMask: [0] };
  }
  // Pondération linéaire entre B04 (665nm) et B11 (1610nm) pour estimer la
  // ligne de base à 842nm (B08), puis FAI = B08 - baseline.
  let baseline = s.B04 + (s.B11 - s.B04) * (842.0 - 665.0) / (1610.0 - 665.0);
  return { default: [s.B08 - baseline], dataMask: [1] };
}
"""


def _appeler_process_api(
    token: str,
    bbox: dict,
    date_debut: date,
    date_fin: date,
    evalscript: str,
    resolution: int,
) -> dict | None:
    """Lance une requête Process API Sentinel Hub et renvoie une statistique
    (moyenne, % positif) à partir des pixels valides.

    Stratégie : on demande l'image elle-même au format TIFF, mais comme cela
    fait beaucoup de données, on préfère utiliser l'API Statistics
    (équivalente, mais agrège côté serveur).
    """
    # On utilise la Statistics API qui renvoie directement des stats agrégées.
    # https://docs.sentinel-hub.com/api/latest/api/statistical/
    statistics_url = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

    bbox_array = [bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"]]

    payload = {
        "input": {
            "bounds": {
                "bbox": bbox_array,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{date_debut.isoformat()}T00:00:00Z",
                            "to": f"{date_fin.isoformat()}T23:59:59Z",
                        },
                        "maxCloudCoverage": COUVERTURE_NUAGEUSE_MAX,
                        "mosaickingOrder": "mostRecent",
                    },
                }
            ],
        },
        "aggregation": {
            "timeRange": {
                "from": f"{date_debut.isoformat()}T00:00:00Z",
                "to": f"{date_fin.isoformat()}T23:59:59Z",
            },
            "aggregationInterval": {"of": "P1D"},
            "evalscript": evalscript,
            "resx": resolution,
            "resy": resolution,
        },
        "calculations": {
            "default": {
                "statistics": {"default": {"percentiles": {"k": [10, 50, 90]}}}
            }
        },
    }

    try:
        reponse = requests.post(
            statistics_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=60,
        )
        reponse.raise_for_status()
        return reponse.json()
    except requests.RequestException as exc:
        corps = ""
        try:
            corps = exc.response.text  # type: ignore[union-attr]
        except Exception:
            pass
        logger.error("Erreur API Statistics : %s | Détail : %s", exc, corps)
        return None


def _extraire_stat_la_plus_recente(reponse_api: dict) -> dict | None:
    """À partir d'une réponse Statistics API, renvoie la dernière mesure
    valide (max date, mean défini, pas seulement NaN)."""
    if not reponse_api:
        return None
    intervalles = reponse_api.get("data", [])
    # On parcourt en commençant par la plus récente
    intervalles_tries = sorted(
        intervalles,
        key=lambda d: d.get("interval", {}).get("from", ""),
        reverse=True,
    )
    for it in intervalles_tries:
        outputs = it.get("outputs", {}).get("default", {}).get("bands", {})
        if not outputs:
            continue
        # Dans la réponse Stats, la bande s'appelle "B0" pour un evalscript single-band
        nom_bande = next(iter(outputs))
        stats = outputs[nom_bande].get("stats", {})
        if stats.get("sampleCount", 0) == 0:
            continue
        return {
            "date_image": it.get("interval", {}).get("from", "")[:10],
            "mean": stats.get("mean"),
            "min": stats.get("min"),
            "max": stats.get("max"),
            "stDev": stats.get("stDev"),
            "sampleCount": stats.get("sampleCount"),
            "noDataCount": stats.get("noDataCount", 0),
        }
    return None


def collecter_indice_site(
    site: dict,
    aujourd_hui: date,
    token: str,
) -> dict:
    """Collecte les indices Sentinel-2 pour les 3 zones d'un site."""
    zones = get_zones(site)
    date_fin = aujourd_hui
    date_debut = aujourd_hui - timedelta(days=FENETRE_RECHERCHE_JOURS)

    resultat = {
        "site_id": site["id"],
        "ndvi_zone_0_estran": None,
        "ndvi_zone_1_cotier": None,
        "fai_zone_2_pelagique": None,
        "image_la_plus_recente": None,
        "avertissement": None,
    }

    # Zone 0 — NDVI estran (10m)
    rep = _appeler_process_api(
        token, zones["zone_0_estran"], date_debut, date_fin,
        EVALSCRIPT_NDVI, resolution=0.0001,
    )
    stat = _extraire_stat_la_plus_recente(rep)
    if stat:
        resultat["ndvi_zone_0_estran"] = stat
        resultat["image_la_plus_recente"] = stat["date_image"]

    # Zone 1 — NDVI côtier (10m)
    rep = _appeler_process_api(
        token, zones["zone_1_cotier"], date_debut, date_fin,
        EVALSCRIPT_NDVI, resolution=0.0001,
    )
    stat = _extraire_stat_la_plus_recente(rep)
    if stat:
        resultat["ndvi_zone_1_cotier"] = stat
        if not resultat["image_la_plus_recente"] or stat["date_image"] > resultat["image_la_plus_recente"]:
            resultat["image_la_plus_recente"] = stat["date_image"]

    # Zone 2 — FAI pélagique (20m, on prend du B11 donc 20m suffit)
    rep = _appeler_process_api(
        token, zones["zone_2_pelagique"], date_debut, date_fin,
        EVALSCRIPT_FAI, resolution=0.0002,
    )
    stat = _extraire_stat_la_plus_recente(rep)
    if stat:
        resultat["fai_zone_2_pelagique"] = stat

    # Avertissement si l'image la plus récente est ancienne
    if resultat["image_la_plus_recente"]:
        try:
            d_img = date.fromisoformat(resultat["image_la_plus_recente"])
            if (aujourd_hui - d_img).days > 5:
                resultat["avertissement"] = (
                    f"Données Sentinel-2 du {d_img.strftime('%d/%m/%Y')} "
                    f"(image la plus récente disponible)"
                )
        except ValueError:
            pass
    else:
        resultat["avertissement"] = "Aucune image Sentinel-2 valide ces 14 derniers jours."

    return resultat


# Evalscript visualisation : couleurs naturelles (B04/B03/B02) avec surimpression
# vert vif sur les pixels eau (SCL=6) où le FAI est positif — seules les masses
# algales flottantes apparaissent en vert, la végétation terrestre reste en couleurs
# naturelles et n'est plus confondue avec les algues.
EVALSCRIPT_IMAGE_RGB = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04", "B08", "B11", "SCL"] }],
    output: { bands: 3, sampleType: "UINT8" }
  };
}
function evaluatePixel(s) {
  // Étirement de contraste pour couleurs naturelles
  function stretch(v) { return Math.min(255, Math.max(0, Math.round(v / 0.35 * 255))); }

  // Pixel eau (SCL=6) avec FAI positif → vert vif = signal algal détecté
  if (s.SCL === 6) {
    let baseline = s.B04 + (s.B11 - s.B04) * (842.0 - 665.0) / (1610.0 - 665.0);
    let fai = s.B08 - baseline;
    if (fai > 0) {
      return [0, 220, 50];
    }
  }

  // Tous les autres pixels : couleurs naturelles (rouge=B04, vert=B03, bleu=B02)
  return [stretch(s.B04), stretch(s.B03), stretch(s.B02)];
}
"""


def _telecharger_image_site(
    token: str,
    bbox: dict,
    date_debut: date,
    date_fin: date,
    chemin_sortie: Path,
    largeur: int = 300,
    hauteur: int = 300,
) -> bool:
    """Télécharge une image JPEG fausse-couleur pour la zone donnée.

    Retourne True si l'image a été enregistrée, False sinon.
    """
    bbox_array = [bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"]]

    payload = {
        "input": {
            "bounds": {
                "bbox": bbox_array,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{date_debut.isoformat()}T00:00:00Z",
                            "to": f"{date_fin.isoformat()}T23:59:59Z",
                        },
                        "maxCloudCoverage": COUVERTURE_NUAGEUSE_MAX,
                        "mosaickingOrder": "mostRecent",
                    },
                }
            ],
        },
        "output": {
            "width": largeur,
            "height": hauteur,
            "responses": [
                {"identifier": "default", "format": {"type": "image/jpeg", "quality": 80}}
            ],
        },
        "evalscript": EVALSCRIPT_IMAGE_RGB,
    }

    try:
        reponse = requests.post(
            CDSE_PROCESS_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "image/jpeg",
            },
            json=payload,
            timeout=60,
        )
        reponse.raise_for_status()
        chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
        chemin_sortie.write_bytes(reponse.content)
        return True
    except requests.RequestException as exc:
        logger.warning("Impossible de télécharger l'image pour %s : %s", chemin_sortie.stem, exc)
        return False


def collecter_tous_les_sites(aujourd_hui: date | None = None) -> dict:
    """Lance la collecte pour tous les sites configurés."""
    charger_env()
    if aujourd_hui is None:
        aujourd_hui = date.today()

    token = _recuperer_token_oauth()
    if not token:
        logger.warning("Mode dégradé : aucune donnée Sentinel-2 ne sera collectée.")
        return {
            "date_collecte": aujourd_hui.isoformat(),
            "statut": "indisponible",
            "raison": "Authentification CDSE impossible (clés manquantes ou erreur réseau).",
            "sites": {},
        }

    # Dossier images : docs/images/YYYY-MM-DD/
    dossier_images = (
        Path(__file__).parent.parent / "docs" / "images" / aujourd_hui.isoformat()
    )

    resultats_par_site = {}
    for site in SITES:
        logger.info("Collecte Sentinel-2 pour %s...", site["id"])
        try:
            res = collecter_indice_site(site, aujourd_hui, token)

            # Téléchargement de la miniature fausse-couleur (zone côtière, 3 km)
            zones = get_zones(site)
            date_debut = aujourd_hui - timedelta(days=FENETRE_RECHERCHE_JOURS)
            chemin_img = dossier_images / f"{site['id']}.jpg"
            ok = _telecharger_image_site(
                token, zones["zone_1_cotier"], date_debut, aujourd_hui, chemin_img
            )
            # Chemin relatif accessible depuis docs/index.html
            res["image_miniature"] = f"images/{aujourd_hui.isoformat()}/{site['id']}.jpg" if ok else None

            resultats_par_site[site["id"]] = res
        except Exception as exc:  # On ne bloque pas le pipeline pour un site
            logger.error("Échec collecte Sentinel-2 site %s : %s", site["id"], exc)
            resultats_par_site[site["id"]] = {
                "site_id": site["id"],
                "ndvi_zone_0_estran": None,
                "ndvi_zone_1_cotier": None,
                "fai_zone_2_pelagique": None,
                "avertissement": f"Erreur collecte : {exc}",
            }

    return {
        "date_collecte": aujourd_hui.isoformat(),
        "statut": "ok",
        "sites": resultats_par_site,
    }


if __name__ == "__main__":
    # Lancement direct : python src/collect_sentinel.py
    donnees = collecter_tous_les_sites()
    chemin = os.path.join(os.path.dirname(__file__), "..", "data", "_sentinel_temp.json")
    enregistrer_json(chemin, donnees)
    logger.info("Collecte Sentinel-2 terminée — %d sites traités", len(donnees.get("sites", {})))
