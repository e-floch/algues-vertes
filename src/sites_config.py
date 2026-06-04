"""
Configuration des sites de surveillance d'algues vertes en Bretagne.

Chaque site est défini par :
  - un identifiant interne (utilisé dans les fichiers JSON)
  - un nom lisible
  - la baie de rattachement
  - une coordonnée GPS centrale (latitude, longitude) en degrés décimaux WGS84
  - le port de référence pour les marées (SHOM)
  - un drapeau "year_round" si la surveillance est demandée toute l'année

Pour ajouter un nouveau site :
  1. Repérer la plage sur Google Maps, clic-droit pour copier les coordonnées
  2. Dupliquer une entrée existante dans la liste SITES ci-dessous
  3. Adapter id, nom, lat/lon, baie et port_maree
  4. Pousser le commit sur GitHub : la prochaine exécution prendra le site en compte
"""
from __future__ import annotations


# Coordonnées GPS centrales de chaque plage (latitude, longitude)
# Les valeurs ont été repérées à partir des cartes IGN / OpenStreetMap.
#
# Champ optionnel `station_airbreizh` : code interne de la station de mesure
# H2S AirBreizh à rattacher (voir STATIONS_AIRBREIZH plus bas). Laisser à None
# si aucune station n'est suffisamment proche pour être représentative.
SITES = [
    # 1. Baie de Guissény
    {
        "id": "guisseny_curnic",
        "nom": "Plage du Curnic",
        "baie": "Baie de Guissény",
        "lat": 48.6464,
        "lon": -4.4133,
        "port_maree": "Brest",
        "year_round": False,
        "station_airbreizh": None,  # Pas de station AirBreizh dans la baie de Guissény
    },
    # 2. Baie de Douarnenez — Nord
    {
        "id": "ploeven_ty_an_quer",
        "nom": "Ploéven — Plage de Ty an Quer",
        "baie": "Baie de Douarnenez (Nord)",
        "lat": 48.1808,
        "lon": -4.3194,
        "port_maree": "Brest",
        "year_round": False,
        "station_airbreizh": "douarnenez_kerleven",
    },
    {
        "id": "plonevez_sainte_anne_la_palud",
        "nom": "Plonévez-Porzay — Plage de Sainte-Anne-la-Palud",
        "baie": "Baie de Douarnenez (Nord)",
        "lat": 48.1583,
        "lon": -4.2800,
        "port_maree": "Brest",
        "year_round": False,
        "station_airbreizh": "douarnenez_kerleven",
    },
    {
        "id": "plonevez_trefeuntec",
        "nom": "Plonévez-Porzay — Anse de Tréfeuntec",
        "baie": "Baie de Douarnenez (Nord)",
        "lat": 48.1486,
        "lon": -4.2664,
        "port_maree": "Brest",
        "year_round": False,
        "station_airbreizh": "douarnenez_kerleven",
    },
    # 2. Baie de Douarnenez — Sud
    {
        "id": "kerlaz_trezmalaouen",
        "nom": "Kerlaz — Plage de Trezmalaouen",
        "baie": "Baie de Douarnenez (Sud)",
        "lat": 48.1086,
        "lon": -4.2772,
        "port_maree": "Brest",
        "year_round": False,
        "station_airbreizh": "douarnenez_ris",
    },
    {
        "id": "douarnenez_ris",
        "nom": "Douarnenez — Plage du Ris",
        "baie": "Baie de Douarnenez (Sud)",
        "lat": 48.1136,
        "lon": -4.3128,
        "port_maree": "Brest",
        "year_round": False,
        "station_airbreizh": "douarnenez_ris",
    },
    # 3. Locquirec — surveillance TOUTE L'ANNÉE
    {
        "id": "locquirec_fond_baie",
        "nom": "Locquirec — Fond de la baie",
        "baie": "Baie de Locquirec",
        "lat": 48.6814,
        "lon": -3.6358,
        "port_maree": "Roscoff",
        "year_round": True,
        "station_airbreizh": "saint_michel_en_greve",
    },
    {
        "id": "locquirec_moulin_de_la_rive",
        "nom": "Locquirec — Moulin de la Rive",
        "baie": "Baie de Locquirec",
        "lat": 48.6928,
        "lon": -3.6622,
        "port_maree": "Roscoff",
        "year_round": True,
        "station_airbreizh": "saint_michel_en_greve",
    },
    # 4. Bassin de Horn-Guillec
    {
        "id": "sibiril_mogueriec",
        "nom": "Sibiril — Moguériec (le port)",
        "baie": "Bassin de Horn-Guillec",
        "lat": 48.6850,
        "lon": -4.0747,
        "port_maree": "Roscoff",
        "year_round": False,
        "station_airbreizh": None,  # Pas de station AirBreizh dans cette baie
    },
    {
        "id": "plougoulm_toul_an_ouch",
        "nom": "Plougoulm — Toul an Ouch",
        "baie": "Bassin de Horn-Guillec",
        "lat": 48.6803,
        "lon": -4.0494,
        "port_maree": "Roscoff",
        "year_round": False,
        "station_airbreizh": None,
    },
    {
        "id": "santec_dossen",
        "nom": "Santec — Plage du Dossen",
        "baie": "Bassin de Horn-Guillec",
        "lat": 48.7044,
        "lon": -4.0356,
        "port_maree": "Roscoff",
        "year_round": False,
        "station_airbreizh": None,
    },
    # 5. Baie de Carantec
    {
        "id": "carantec",
        "nom": "Carantec — Plage de Pen al Lann",
        "baie": "Baie de Carantec",
        "lat": 48.6739,
        "lon": -3.9119,
        "port_maree": "Roscoff",
        "year_round": False,
        "station_airbreizh": None,
    },
]


# ----------------------------------------------------------------------
# Stations AirBreizh du réseau "Algues Vertes" (mesures H2S)
# ----------------------------------------------------------------------
# AirBreizh exploite, du 15 mai au 15 octobre, un réseau d'environ 17 points
# de mesure horaire de H2S dans les baies bretonnes touchées par les algues
# vertes (sources : rapports annuels AirBreizh).
#
# La liste ci-dessous contient les stations qu'il est probable de retrouver
# dans le flux WFS. Le champ "code_wfs" est le nom de la station tel qu'il
# apparaît dans l'attribut "nom_station" (ou équivalent) du flux WFS d'AirBreizh.
#
# Pour vérifier la liste complète et ajuster les codes :
#   1. Ouvrir la fiche de métadonnées :
#      https://opendata.airbreizh.asso.fr/geonetwork/srv/fre/catalog.search#/metadata/353f3c26-c35e-434f-afd3-f54e0ae5e0ef
#   2. Récupérer l'URL du service WFS et appeler GetCapabilities pour lister
#      les types et attributs réellement publiés.
#   3. Mettre à jour les champs "code_wfs" et coordonnées si besoin.
STATIONS_AIRBREIZH = {
    "saint_michel_en_greve": {
        "nom": "Saint-Michel-en-Grève",
        "baie": "Baie de Lannion / Locquirec",
        "lat": 48.6850,
        "lon": -3.5650,
        "code_wfs": "Saint-Michel-en-Grève",
    },
    "plestin_les_greves": {
        "nom": "Plestin-les-Grèves",
        "baie": "Baie de Lannion",
        "lat": 48.6608,
        "lon": -3.6253,
        "code_wfs": "Plestin-les-Grèves",
    },
    "tredrez_locquemeau": {
        "nom": "Trédrez-Locquémeau",
        "baie": "Baie de Lannion",
        "lat": 48.7167,
        "lon": -3.5781,
        "code_wfs": "Trédrez-Locquémeau",
    },
    "douarnenez_kerleven": {
        "nom": "Douarnenez — Kerléven",
        "baie": "Baie de Douarnenez",
        "lat": 48.1083,
        "lon": -4.3258,
        "code_wfs": "Douarnenez Kerléven",
    },
    "douarnenez_ris": {
        "nom": "Douarnenez — Plage du Ris",
        "baie": "Baie de Douarnenez",
        "lat": 48.1136,
        "lon": -4.3128,
        "code_wfs": "Douarnenez Le Ris",
    },
    "hillion": {
        "nom": "Hillion — Anse d'Yffiniac",
        "baie": "Baie de Saint-Brieuc",
        "lat": 48.5072,
        "lon": -2.6797,
        "code_wfs": "Hillion",
    },
    "morieux": {
        "nom": "Morieux — Saint-Maurice",
        "baie": "Baie de Saint-Brieuc",
        "lat": 48.5400,
        "lon": -2.6300,
        "code_wfs": "Morieux",
    },
    "binic_etables": {
        "nom": "Binic — Étables-sur-Mer",
        "baie": "Baie de Saint-Brieuc (nord)",
        "lat": 48.5933,
        "lon": -2.8278,
        "code_wfs": "Étables-sur-Mer",
    },
}


# ----------------------------------------------------------------------
# Seuils sanitaires H2S (référence OMS / INERIS)
# ----------------------------------------------------------------------
# Valeurs en µg/m³ — utilisées pour colorer les concentrations affichées.
SEUILS_H2S = [
    {"max": 5,    "niveau": "négligeable", "couleur": "#3CB371",
     "desc": "Niveau de fond, sans odeur perceptible."},
    {"max": 50,   "niveau": "perceptible", "couleur": "#A8D86C",
     "desc": "Odeur d'œuf pourri perceptible, sans effet sanitaire."},
    {"max": 100,  "niveau": "gênant",      "couleur": "#F1C40F",
     "desc": "Valeur guide OMS pour une exposition de 1 heure."},
    {"max": 1000, "niveau": "élevé",       "couleur": "#E67E22",
     "desc": "Inconfort net, risque d'irritation des voies respiratoires."},
    {"max": float("inf"), "niveau": "dangereux", "couleur": "#C0392B",
     "desc": "Concentration potentiellement dangereuse — intervention urgente."},
]


def classifier_h2s(valeur_ug_m3: "float | None") -> "dict | None":
    """Renvoie le seuil sanitaire H2S correspondant à une concentration."""
    if valeur_ug_m3 is None:
        return None
    for seuil in SEUILS_H2S:
        if valeur_ug_m3 < seuil["max"]:
            return seuil
    return SEUILS_H2S[-1]


# ----------------------------------------------------------------------
# Calcul automatique des bounding boxes pour les zones Sentinel-2
# ----------------------------------------------------------------------

def _bbox_around(lat: float, lon: float, demi_largeur_km: float) -> dict:
    """Renvoie une bounding box (min_lon, min_lat, max_lon, max_lat)
    centrée sur (lat, lon) avec une demi-largeur donnée en kilomètres.

    Approximation simple :
      - 1° de latitude ≈ 111 km
      - 1° de longitude ≈ 111 km × cos(latitude)

    Suffisante pour la Bretagne (latitude ~48°, faible déformation).
    """
    import math

    deg_par_km_lat = 1.0 / 111.0
    deg_par_km_lon = 1.0 / (111.0 * math.cos(math.radians(lat)))

    delta_lat = demi_largeur_km * deg_par_km_lat
    delta_lon = demi_largeur_km * deg_par_km_lon

    return {
        "min_lon": round(lon - delta_lon, 6),
        "min_lat": round(lat - delta_lat, 6),
        "max_lon": round(lon + delta_lon, 6),
        "max_lat": round(lat + delta_lat, 6),
    }


def get_zones(site: dict) -> dict:
    """Renvoie les 3 zones de collecte Sentinel-2 pour un site donné.

    - Zone 0 : emprise de la plage (~250 m de large, soit ~0,06 km²)
    - Zone 1 : production côtière, rayon 3 km (~28 km², on prend bbox 3 km
               de demi-largeur ce qui correspond à un carré de 6 km × 6 km)
    - Zone 2 : transit pélagique, rayon 15 km (carré de 30 km × 30 km),
               à laquelle on retire la zone 1 conceptuellement
    """
    return {
        "zone_0_estran": _bbox_around(site["lat"], site["lon"], 0.125),
        "zone_1_cotier": _bbox_around(site["lat"], site["lon"], 3.0),
        "zone_2_pelagique": _bbox_around(site["lat"], site["lon"], 15.0),
    }


def get_site_by_id(site_id: str) -> "dict | None":
    """Recherche un site par son identifiant."""
    for site in SITES:
        if site["id"] == site_id:
            return site
    return None


# ----------------------------------------------------------------------
# Pondération du score de risque (modifiable par calibrage manuel)
# ----------------------------------------------------------------------
# Ces poids peuvent être ajustés via la fonction calibrate() de compute_risk.py
# au fur et à mesure que des observations terrain seront disponibles.
POIDS_FACTEURS_DEFAUT = {
    "fai_zone_2": 0.40,      # Masse algale flottante en mer
    "vent": 0.30,            # Vent favorable à l'échouage
    "coef_maree": 0.20,      # Coefficient de marée (vives-eaux = +)
    "ndvi_zone_1": 0.10,     # Biomasse en zone côtière 1
}


# ----------------------------------------------------------------------
# Seuils des niveaux d'alerte
# ----------------------------------------------------------------------
NIVEAUX_ALERTE = [
    {"min": 0,  "max": 25,  "niveau": 1, "nom": "Veille",
     "couleur": "#3CB371",
     "description": "Conditions favorables à la croissance, aucun échouage imminent."},
    {"min": 26, "max": 50,  "niveau": 2, "nom": "Vigilance",
     "couleur": "#F1C40F",
     "description": "Masse algale détectée en mer, échouage possible sous 72h."},
    {"min": 51, "max": 75,  "niveau": 3, "nom": "Alerte",
     "couleur": "#E67E22",
     "description": "Échouage probable sous 48h, mobilisation recommandée."},
    {"min": 76, "max": 100, "niveau": 4, "nom": "Critique",
     "couleur": "#C0392B",
     "description": "Échouage imminent sous 24h, intervention nécessaire."},
]


def niveau_alerte_pour_score(score: float) -> dict:
    """Renvoie l'entrée de NIVEAUX_ALERTE correspondant au score donné.

    On cherche le premier niveau dont le score ne dépasse pas le max —
    les seuils étant ordonnés, cela couvre tous les flottants sans trou.
    """
    if score < 0:
        return NIVEAUX_ALERTE[0]
    for niveau in NIVEAUX_ALERTE:
        if score <= niveau["max"]:
            return niveau
    return NIVEAUX_ALERTE[-1]
