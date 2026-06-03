"""
Collecte des mesures horaires d'hydrogène sulfuré (H2S) issues du réseau
"Algues vertes" d'AirBreizh, via leur service WFS (Web Feature Service).

Le H2S est utilisé ici comme **indicateur observé d'échouage en cours** —
il n'entre pas dans le calcul du score prédictif J+1→J+7, mais s'affiche
en complément dans le panneau de détail de chaque site rattaché à une
station de mesure AirBreizh.

Caractéristiques du flux :
  - Source : AirBreizh (AASQA Bretagne)
  - Fiche métadonnée : https://opendata.airbreizh.asso.fr/geonetwork/srv/fre/catalog.search#/metadata/353f3c26-c35e-434f-afd3-f54e0ae5e0ef
  - Couverture : 17 points de mesure dans 7 baies bretonnes
  - Période : du 15 mai au 15 octobre (hors saison → pas de données)
  - Fréquence : moyenne horaire, mise à jour mensuelle (mois M-1 publié début M)
  - Format : GML 3.1 ou JSON via WFS standard (OGC)

Configuration :
  - Variable d'environnement AIRBREIZH_WFS_URL = URL du service WFS
  - Variable AIRBREIZH_LAYER (optionnel) = nom de la couche/typename
  - Si non configuré → on tente l'URL par défaut documentée par AirBreizh,
    mais le pipeline ne plante pas en cas d'échec.

En l'absence de données (hors saison, service indisponible), la fonction
renvoie None et le tableau de bord affiche "Pas de mesure H2S disponible".
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests

from sites_config import SITES, STATIONS_AIRBREIZH, classifier_h2s
from utils import charger_env, get_logger

logger = get_logger("collect_airbreizh")

# URL par défaut du service WFS AirBreizh (à confirmer via la fiche de
# métadonnées 353f3c26-c35e-434f-afd3-f54e0ae5e0ef). Surchargée par la
# variable d'environnement AIRBREIZH_WFS_URL si elle est définie.
WFS_URL_DEFAUT = "https://opendata.airbreizh.asso.fr/geoserver/airbreizh/wfs"
LAYER_DEFAUT = "airbreizh:concentration_horaire_h2s"

# Période active du réseau AirBreizh Algues Vertes
SAISON_DEBUT = (5, 15)   # 15 mai
SAISON_FIN = (10, 15)    # 15 octobre


def _en_saison(aujourd_hui: date) -> bool:
    """Renvoie True si la date est dans la fenêtre de surveillance estivale."""
    d_debut = date(aujourd_hui.year, *SAISON_DEBUT)
    d_fin = date(aujourd_hui.year, *SAISON_FIN)
    return d_debut <= aujourd_hui <= d_fin


def _appel_wfs(url: str, layer: str, depuis: date, jusqu_a: date) -> list[dict] | None:
    """Appelle le service WFS avec pagination pour couvrir toutes les stations.

    On pagine par blocs de 5000 jusqu'à avoir collecté des mesures pour
    toutes les stations connues ou atteint 10 pages (50 000 entrées max).
    """
    PAGE = 5000
    MAX_PAGES = 10
    toutes = []
    stations_connues = {
        _normaliser(v["code_wfs"]) for v in STATIONS_AIRBREIZH.values()
    }

    for page in range(MAX_PAGES):
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": layer,
            "count": str(PAGE),
            "startIndex": str(page * PAGE),
        }
        try:
            rep = requests.get(url, params=params, timeout=60)
            rep.raise_for_status()
            mesures_page = _parser_gml(rep.text)
            if not mesures_page:
                break  # plus de données
            toutes.extend(mesures_page)

            # Vérifier si on a toutes les stations nécessaires
            stations_recues = {_normaliser(m["station"]) for m in toutes}
            if stations_connues.issubset(stations_recues):
                logger.info("Toutes les stations trouvées à la page %d", page + 1)
                break
        except requests.RequestException as exc:
            logger.error("Échec appel WFS AirBreizh (page %d) : %s", page, exc)
            return None if not toutes else toutes

    logger.info("AirBreizh WFS : %d mesures reçues au total", len(toutes))
    return toutes or None


def _extraire_feature_json(feature: dict) -> dict | None:
    """Extrait nom station / date / valeur d'une feature GeoJSON.

    Les noms d'attributs WFS varient d'une AASQA à l'autre. On essaie
    plusieurs alias usuels.
    """
    props = feature.get("properties", {}) or {}

    def _first(*cles):
        for c in cles:
            if c in props and props[c] not in (None, ""):
                return props[c]
        return None

    station = _first("nom_station", "station", "lib_station", "nom_site")
    valeur = _first("valeur", "value", "concentration", "h2s")
    horodate = _first("date_debut", "date", "date_mesure", "timestamp")

    if station is None or valeur is None or horodate is None:
        return None

    try:
        valeur = float(valeur)
    except (TypeError, ValueError):
        return None

    return {"station": str(station), "valeur": valeur, "horodate": str(horodate)}


def _parser_gml(xml_text: str) -> list[dict]:
    """Parse une réponse GML MapServer AirBreizh.

    Structure attendue :
      <ms:mes_bretagne_horaire_h2s>
        <ms:nom_station>H2S_C6_Hoteller</ms:nom_station>
        <ms:valeur>0.001</ms:valeur>          ← en ppm
        <ms:unite>ppm</ms:unite>
        <ms:date_debut><gml:timePosition>2025-06-03T00:00:00Z</gml:timePosition></ms:date_debut>
      </ms:mes_bretagne_horaire_h2s>

    Conversion ppm → µg/m³ : 1 ppm H2S ≈ 1400 µg/m³ (à 20°C, pression atm).
    """
    PPM_EN_UG_M3 = 1400.0  # facteur de conversion approximatif H2S
    resultats = []
    try:
        racine = ET.fromstring(xml_text)
    except ET.ParseError:
        return resultats

    for elem in racine.iter():
        tag = elem.tag.split("}", 1)[-1].lower()
        # On cible les éléments feature de la couche h2s
        if "h2s" not in tag:
            continue
        bloc = {}
        for enfant in elem:
            t = enfant.tag.split("}", 1)[-1].lower()
            if t == "nom_station":
                bloc["station"] = (enfant.text or "").strip()
            elif t == "nom_com":
                bloc["commune"] = (enfant.text or "").strip().title()
            elif t == "x_wgs84":
                try:
                    bloc["lon"] = float((enfant.text or "").strip())
                except ValueError:
                    pass
            elif t == "y_wgs84":
                try:
                    bloc["lat"] = float((enfant.text or "").strip())
                except ValueError:
                    pass
            elif t == "valeur":
                try:
                    bloc["valeur_ppm"] = float((enfant.text or "").strip())
                except ValueError:
                    pass
            elif t == "unite":
                bloc["unite"] = (enfant.text or "").strip().lower()
            elif t == "date_debut":
                # La date est dans un enfant gml:timePosition
                for petit_enfant in enfant:
                    pt = petit_enfant.tag.split("}", 1)[-1].lower()
                    if pt == "timeposition":
                        bloc["horodate"] = (petit_enfant.text or "").strip()
                        break
                # Fallback si texte direct
                if "horodate" not in bloc and enfant.text:
                    bloc["horodate"] = enfant.text.strip()

        if {"station", "valeur_ppm", "horodate"}.issubset(bloc):
            # Conversion en µg/m³
            unite = bloc.get("unite", "ppm")
            if unite == "ppm":
                valeur_ug = bloc["valeur_ppm"] * PPM_EN_UG_M3
            else:
                valeur_ug = bloc["valeur_ppm"]  # déjà en µg/m³
            # Clé = commune si disponible, sinon code station
            cle = bloc.get("commune", bloc["station"])
            resultats.append({
                "station": cle,
                "station_code": bloc["station"],
                "commune": bloc.get("commune", ""),
                "lat": bloc.get("lat"),
                "lon": bloc.get("lon"),
                "valeur": round(valeur_ug, 2),
                "horodate": bloc["horodate"],
            })
    return resultats


def _agreger_par_station(mesures: list[dict]) -> dict[str, dict]:
    """Pour chaque station, calcule la dernière mesure, la moyenne 24h
    et la max 7 jours."""
    par_station: dict[str, list[dict]] = {}
    for m in mesures:
        par_station.setdefault(m["station"], []).append(m)

    resultats = {}
    for station_nom, liste in par_station.items():
        # Tri chronologique
        liste_triee = sorted(liste, key=lambda x: x["horodate"])
        if not liste_triee:
            continue
        derniere = liste_triee[-1]
        try:
            t_derniere = datetime.fromisoformat(derniere["horodate"].replace("Z", "+00:00"))
        except ValueError:
            t_derniere = None

        # Sous-ensembles 24h et 7j (basés sur la dernière mesure)
        valeurs_24h = []
        valeurs_7j = []
        if t_derniere:
            for m in liste_triee:
                try:
                    t = datetime.fromisoformat(m["horodate"].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if (t_derniere - t).total_seconds() <= 24 * 3600:
                    valeurs_24h.append(m["valeur"])
                if (t_derniere - t).total_seconds() <= 7 * 24 * 3600:
                    valeurs_7j.append(m["valeur"])
        else:
            valeurs_24h = [m["valeur"] for m in liste_triee[-24:]]
            valeurs_7j = [m["valeur"] for m in liste_triee[-168:]]

        # Coordonnées : on prend celles de la première mesure qui en a
        lat_station = next((m["lat"] for m in liste_triee if m.get("lat")), None)
        lon_station = next((m["lon"] for m in liste_triee if m.get("lon")), None)

        resultats[station_nom] = {
            "nom": station_nom,
            "lat": lat_station,
            "lon": lon_station,
            "derniere_mesure_ug_m3": round(derniere["valeur"], 1),
            "horodate_derniere_mesure": derniere["horodate"],
            "moyenne_24h_ug_m3": round(sum(valeurs_24h) / len(valeurs_24h), 1) if valeurs_24h else None,
            "max_7j_ug_m3": round(max(valeurs_7j), 1) if valeurs_7j else None,
            "nb_mesures_7j": len(valeurs_7j),
        }
    return resultats


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance approximative en km entre deux points (formule haversine simplifiée)."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _associer_aux_sites(par_station_wfs: dict[str, dict]) -> dict[str, dict]:
    """Associe chaque site de surveillance à la station AirBreizh la plus proche."""
    # Filtrer les stations qui ont des coordonnées
    stations_avec_coords = {
        nom: data for nom, data in par_station_wfs.items()
        if data.get("lat") and data.get("lon")
    }

    par_site = {}
    for site in SITES:
        if not stations_avec_coords:
            par_site[site["id"]] = {
                "site_id": site["id"], "station": None, "mesure": None,
                "raison": "Aucune station AirBreizh avec coordonnées disponible.",
            }
            continue

        # Trouver la station la plus proche
        site_lat, site_lon = site["lat"], site["lon"]
        station_proche = min(
            stations_avec_coords.items(),
            key=lambda kv: _distance_km(site_lat, site_lon, kv[1]["lat"], kv[1]["lon"])
        )
        nom_station, donnees_station = station_proche
        dist_km = _distance_km(site_lat, site_lon, donnees_station["lat"], donnees_station["lon"])

        mesure = {k: v for k, v in donnees_station.items() if k not in ("lat", "lon", "nom")}
        seuil = classifier_h2s(mesure.get("derniere_mesure_ug_m3"))
        mesure["niveau_sanitaire"] = seuil["niveau"] if seuil else None
        mesure["couleur"] = seuil["couleur"] if seuil else None
        mesure["description_seuil"] = seuil["desc"] if seuil else None
        mesure["distance_km"] = round(dist_km, 1)

        par_site[site["id"]] = {
            "site_id": site["id"],
            "station": {
                "nom": nom_station,
                "lat": donnees_station["lat"],
                "lon": donnees_station["lon"],
                "distance_km": round(dist_km, 1),
            },
            "mesure": mesure,
            "raison": None,
        }
    return par_site


def _normaliser(s: str) -> str:
    """Normalisation pour comparaison de noms de station (sans accent ni casse)."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace("-", " ").replace("_", " ").strip()


# ----------------------------------------------------------------------
# Point d'entrée principal
# ----------------------------------------------------------------------

def collecter_tous_les_sites(aujourd_hui: date | None = None) -> dict:
    """Lance la collecte H2S et associe les mesures aux sites de surveillance."""
    charger_env()
    if aujourd_hui is None:
        aujourd_hui = date.today()

    en_saison = _en_saison(aujourd_hui)

    # Hors saison : on n'appelle pas le service, on renvoie tout à vide proprement
    if not en_saison:
        return {
            "date_collecte": aujourd_hui.isoformat(),
            "statut": "hors_saison",
            "avertissement": (
                "Réseau AirBreizh H2S Algues Vertes inactif "
                "(opérationnel du 15 mai au 15 octobre)."
            ),
            "sites": {
                site["id"]: {
                    "site_id": site["id"],
                    "station": None,
                    "mesure": None,
                    "raison": "Hors saison de surveillance H2S.",
                }
                for site in SITES
            },
        }

    url = os.environ.get("AIRBREIZH_WFS_URL", WFS_URL_DEFAUT)
    layer = os.environ.get("AIRBREIZH_LAYER", LAYER_DEFAUT)

    # On recherche jusqu'à 30 jours en arrière pour absorber le délai de
    # publication mensuelle d'AirBreizh.
    mesures = _appel_wfs(url, layer, aujourd_hui - timedelta(days=30), aujourd_hui)
    if mesures is None:
        return {
            "date_collecte": aujourd_hui.isoformat(),
            "statut": "indisponible",
            "avertissement": (
                "Service WFS AirBreizh injoignable. Vérifier AIRBREIZH_WFS_URL "
                "dans la configuration (.env ou GitHub Secret)."
            ),
            "sites": {
                site["id"]: {"site_id": site["id"], "station": None, "mesure": None,
                             "raison": "Service AirBreizh indisponible."}
                for site in SITES
            },
        }

    logger.info("AirBreizh : %d mesures récupérées sur 30 jours", len(mesures))
    par_station = _agreger_par_station(mesures)
    par_site = _associer_aux_sites(par_station)

    return {
        "date_collecte": aujourd_hui.isoformat(),
        "statut": "ok",
        "source": "AirBreizh — Réseau Algues Vertes (H2S horaire)",
        "url_wfs": url,
        "nb_stations_retournees": len(par_station),
        "sites": par_site,
    }


if __name__ == "__main__":
    from utils import enregistrer_json
    donnees = collecter_tous_les_sites()
    chemin = os.path.join(os.path.dirname(__file__), "..", "data", "_airbreizh_temp.json")
    enregistrer_json(chemin, donnees)
    logger.info("Collecte AirBreizh terminée — statut : %s", donnees.get("statut"))
