"""
Calcul du score et du niveau de risque d'échouage d'algues vertes.

Modèle de score (0 à 100) à partir de 4 facteurs pondérés :
  - FAI moyen en zone 2 (40 %)         — masse algale flottante en mer
  - Vent favorable à l'échouage (30 %) — direction et force
  - Coefficient de marée (20 %)        — vives-eaux = +
  - NDVI moyen en zone 1 (10 %)        — biomasse en zone côtière

Si une donnée est manquante, le poids correspondant est redistribué
sur les autres facteurs proportionnellement.

La fonction `calibrate(site_id, date_obs, niveau_observe)` permet d'ajuster
les pondérations à partir d'observations terrain.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from sites_config import (
    NIVEAUX_ALERTE,
    POIDS_FACTEURS_DEFAUT,
    SITES,
    get_site_by_id,
    niveau_alerte_pour_score,
)
from utils import (
    DOSSIER_DATA,
    charger_json,
    enregistrer_json,
    get_logger,
)

logger = get_logger("compute_risk")

# Fichier où sont enregistrées les pondérations calibrées
FICHIER_CALIBRATION = DOSSIER_DATA.parent / "calibration.json"


# ----------------------------------------------------------------------
# Direction de vent favorable à l'échouage par baie
# ----------------------------------------------------------------------
# Pour chaque baie, on associe une plage de directions (en degrés, depuis
# laquelle souffle le vent — convention météo) qui pousse l'eau et les
# algues flottantes vers les plages.
VENT_FAVORABLE_PAR_BAIE = {
    "Baie de Guissény":           {"min": 270, "max": 360, "min2": 0,   "max2": 30},   # vent de NW
    "Baie de Douarnenez (Nord)":  {"min": 180, "max": 270},                              # vent de SW
    "Baie de Douarnenez (Sud)":   {"min": 270, "max": 360},                              # vent de NW
    "Baie de Locquirec":          {"min": 0,   "max": 90},                               # vent de NE
    "Bassin de Horn-Guillec":     {"min": 0,   "max": 60,  "min2": 300, "max2": 360},  # vent de N à NE
    "Baie de Carantec":           {"min": 0,   "max": 60,  "min2": 300, "max2": 360},  # vent de N à NE
}


# ----------------------------------------------------------------------
# Fonctions de scoring par facteur (chacune renvoie une valeur 0-100)
# ----------------------------------------------------------------------

def _score_fai(donnees_sentinel: "dict | None") -> "float | None":
    """Score 0-100 d'après le FAI moyen en zone 2 pélagique.

    Heuristique : FAI > 0,01 indique de la matière flottante. On normalise
    sur une échelle 0..100 avec saturation à FAI = 0,1.
    """
    if not donnees_sentinel:
        return None
    fai = donnees_sentinel.get("fai_zone_2_pelagique")
    if not fai or fai.get("mean") is None:
        return None
    val = fai["mean"]
    # Linéaire avec saturation : 0 → 0, 0,1 → 100
    score = max(0.0, min(100.0, val * 1000))
    return round(score, 1)


def _score_ndvi(donnees_sentinel: "dict | None") -> "float | None":
    """Score 0-100 d'après le NDVI moyen en zone 1 (biomasse côtière).

    Heuristique : NDVI < 0,1 (faible), 0,1-0,3 (moyen), > 0,3 (fort) sur
    pixels d'estran. On linéarise sur 0..100 avec saturation à 0,4.
    """
    if not donnees_sentinel:
        return None
    ndvi = donnees_sentinel.get("ndvi_zone_1_cotier")
    if not ndvi or ndvi.get("mean") is None:
        return None
    val = ndvi["mean"]
    score = max(0.0, min(100.0, val * 250))
    return round(score, 1)


def _score_vent(donnees_meteo: "dict | None", baie: str, jour: date) -> "float | None":
    """Score 0-100 d'après la prévision de vent pour le jour cible.

    Combine direction (vent depuis le large = +) et force (10-25 km/h = optimal,
    >40 km/h = mer trop agitée, on ne sait plus).
    """
    if not donnees_meteo or not donnees_meteo.get("previsions"):
        return None

    prev = next(
        (p for p in donnees_meteo["previsions"] if p["date"] == jour.isoformat()),
        None,
    )
    if not prev or prev.get("vent_moyen_kmh") is None:
        return None

    # 1. Score direction
    direction = prev["direction_dominante_deg"]
    fav = VENT_FAVORABLE_PAR_BAIE.get(baie, {})
    favorable = False
    if "min" in fav and fav["min"] <= direction <= fav["max"]:
        favorable = True
    if "min2" in fav and fav["min2"] <= direction <= fav["max2"]:
        favorable = True
    score_dir = 100 if favorable else 30

    # 2. Score force (cloche entre 10 et 25 km/h)
    v = prev["vent_moyen_kmh"]
    if v <= 5 or v >= 50:
        score_force = 10
    elif 10 <= v <= 25:
        score_force = 100
    elif v < 10:
        score_force = 100 * v / 10
    else:  # 25 < v < 50
        score_force = max(0, 100 - (v - 25) * 4)

    return round(0.6 * score_dir + 0.4 * score_force, 1)


def _score_coef_maree(donnees_maree: "dict | None", jour: date) -> "float | None":
    """Score 0-100 d'après le coefficient de marée du jour.

    Coef 20-50 (mortes-eaux) → 20 ; 50-80 (moyen) → 50 ; 80-120 (vives-eaux) → 100.
    """
    if not donnees_maree or not donnees_maree.get("previsions"):
        return None

    prev = next(
        (p for p in donnees_maree["previsions"] if p["date"] == jour.isoformat()),
        None,
    )
    if not prev or prev.get("coefficient") is None:
        return None

    coef = prev["coefficient"]
    # Linéaire de 20 (score 0) à 120 (score 100)
    score = max(0.0, min(100.0, (coef - 20) / 100 * 100))
    return round(score, 1)


# ----------------------------------------------------------------------
# Combinaison pondérée
# ----------------------------------------------------------------------

def _charger_poids() -> dict:
    """Charge les poids calibrés (ou ceux par défaut)."""
    cal = charger_json(FICHIER_CALIBRATION)
    if cal and "poids" in cal:
        return cal["poids"]
    return dict(POIDS_FACTEURS_DEFAUT)


def _combiner_scores(scores: dict, poids: dict) -> tuple[float | None, dict]:
    """Combine les scores avec leurs poids. Si un score est None, on
    redistribue son poids sur les autres facteurs."""
    correspondance = {
        "fai_zone_2": scores.get("fai"),
        "vent": scores.get("vent"),
        "coef_maree": scores.get("coef_maree"),
        "ndvi_zone_1": scores.get("ndvi"),
    }

    facteurs_disponibles = {k: v for k, v in correspondance.items() if v is not None}
    if not facteurs_disponibles:
        return None, {}

    poids_totaux = sum(poids[k] for k in facteurs_disponibles)
    if poids_totaux == 0:
        return None, {}

    score_brut = sum(
        facteurs_disponibles[k] * poids[k] / poids_totaux
        for k in facteurs_disponibles
    )

    detail = {
        k: {
            "valeur": correspondance[k],
            "poids_applique": round(poids[k] / poids_totaux, 3) if k in facteurs_disponibles else 0,
            "disponible": k in facteurs_disponibles,
        }
        for k in correspondance
    }
    return round(score_brut, 1), detail


# ----------------------------------------------------------------------
# Calcul du risque pour un site et un horizon J+1..J+7
# ----------------------------------------------------------------------

def calculer_risque_site(
    site: dict,
    donnees_sentinel: dict,
    donnees_meteo: dict,
    donnees_maree: dict,
    aujourd_hui: date,
) -> dict:
    """Calcule les niveaux de risque J+1..J+7 pour un site donné."""
    poids = _charger_poids()
    previsions = []

    for offset in range(1, 8):  # J+1 à J+7
        jour_cible = aujourd_hui + timedelta(days=offset)

        scores_facteurs = {
            "fai": _score_fai(donnees_sentinel),
            "ndvi": _score_ndvi(donnees_sentinel),
            "vent": _score_vent(donnees_meteo, site["baie"], jour_cible),
            "coef_maree": _score_coef_maree(donnees_maree, jour_cible),
        }

        score_global, detail = _combiner_scores(scores_facteurs, poids)
        niveau = niveau_alerte_pour_score(score_global) if score_global is not None else None

        previsions.append({
            "horizon": f"J+{offset}",
            "date": jour_cible.isoformat(),
            "score": score_global,
            "niveau": niveau["niveau"] if niveau else None,
            "nom_niveau": niveau["nom"] if niveau else "Indisponible",
            "couleur": niveau["couleur"] if niveau else "#888888",
            "facteurs": detail,
        })

    return {
        "site_id": site["id"],
        "site_nom": site["nom"],
        "baie": site["baie"],
        "lat": site["lat"],
        "lon": site["lon"],
        "year_round": site["year_round"],
        "previsions": previsions,
    }


# ----------------------------------------------------------------------
# Pipeline complet : produit l'objet JSON du jour à archiver
# ----------------------------------------------------------------------

def construire_etat_du_jour(
    donnees_sentinel: dict,
    donnees_meteo: dict,
    donnees_maree: dict,
    aujourd_hui: date | None = None,
    donnees_airbreizh: "dict | None" = None,
) -> dict:
    """Construit l'objet JSON complet pour la date du jour.

    `donnees_airbreizh` (optionnel) : mesures H2S issues d'AirBreizh.
    Elles sont ajoutées au panneau de détail mais n'entrent **pas** dans
    le calcul du score prédictif (le H2S est un indicateur observé, pas
    une prévision).
    """
    if aujourd_hui is None:
        aujourd_hui = date.today()

    sites_resultats = []
    for site in SITES:
        s_sent = donnees_sentinel.get("sites", {}).get(site["id"], {})
        s_meteo = donnees_meteo.get("sites", {}).get(site["id"], {})
        s_maree = donnees_maree.get("sites", {}).get(site["id"], {})
        s_air = (donnees_airbreizh or {}).get("sites", {}).get(site["id"], {})

        risque = calculer_risque_site(
            site,
            s_sent,
            s_meteo,
            s_maree,
            aujourd_hui,
        )
        risque["sentinel"] = {
            "image_la_plus_recente": s_sent.get("image_la_plus_recente"),
            "image_miniature": s_sent.get("image_miniature"),
            "ndvi_zone_0": s_sent.get("ndvi_zone_0_estran"),
            "ndvi_zone_1": s_sent.get("ndvi_zone_1_cotier"),
            "fai_zone_2": s_sent.get("fai_zone_2_pelagique"),
            "avertissement": s_sent.get("avertissement"),
        }
        risque["meteo"] = {
            "source": s_meteo.get("source"),
            "previsions": s_meteo.get("previsions", []),
            "avertissement": s_meteo.get("avertissement"),
        }
        risque["maree"] = {
            "port": s_maree.get("port"),
            "previsions": s_maree.get("previsions", []),
            "avertissement": s_maree.get("avertissement"),
        }
        # Bloc "airbreizh" : peut contenir une station + mesure, ou juste une raison
        risque["airbreizh"] = {
            "station": s_air.get("station") if s_air else None,
            "mesure": s_air.get("mesure") if s_air else None,
            "raison": s_air.get("raison") if s_air else "Données AirBreizh non collectées.",
        }
        sites_resultats.append(risque)

    avertissements_globaux = []
    if donnees_sentinel.get("statut") != "ok":
        avertissements_globaux.append(
            "Données Sentinel-2 indisponibles aujourd'hui : "
            f"{donnees_sentinel.get('raison', 'erreur inconnue')}"
        )
    if donnees_airbreizh and donnees_airbreizh.get("statut") not in ("ok", "hors_saison", None):
        avertissements_globaux.append(
            "Données AirBreizh H2S indisponibles : "
            f"{donnees_airbreizh.get('avertissement', 'erreur inconnue')}"
        )

    return {
        "date": aujourd_hui.isoformat(),
        "horodatage_generation_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "sites": sites_resultats,
        "avertissements_globaux": avertissements_globaux,
        "poids_appliques": _charger_poids(),
        "airbreizh_statut": (donnees_airbreizh or {}).get("statut"),
    }


# ----------------------------------------------------------------------
# Calibration manuelle
# ----------------------------------------------------------------------

def calibrate(site_id: str, date_obs: date, niveau_observe: int) -> dict:
    """Enregistre une observation terrain et ajuste les pondérations.

    Algorithme simple : on compare le score prédit J pour le site donné au
    niveau observé sur le terrain. Si la prédiction sur-estime (resp. sous-
    estime), on diminue (resp. augmente) légèrement le poids du facteur
    qui contribue le plus.

    Args:
        site_id      : identifiant du site (ex: "guisseny_curnic")
        date_obs     : date de l'observation (date)
        niveau_observe : niveau réel observé (1, 2, 3 ou 4)

    Returns:
        Le dict des nouveaux poids enregistrés.
    """
    site = get_site_by_id(site_id)
    if not site:
        raise ValueError(f"Site inconnu : {site_id}")
    if niveau_observe not in (1, 2, 3, 4):
        raise ValueError("niveau_observe doit valoir 1, 2, 3 ou 4")

    fichier_jour = DOSSIER_DATA / f"{date_obs.isoformat()}.json"
    etat = charger_json(fichier_jour)
    if not etat:
        raise FileNotFoundError(f"Aucune donnée disponible pour {date_obs}")

    site_data = next((s for s in etat["sites"] if s["site_id"] == site_id), None)
    if not site_data or not site_data["previsions"]:
        raise ValueError(f"Aucune prévision pour {site_id} le {date_obs}")

    # On compare la prévision J+1 (la plus proche) au niveau observé
    pred = site_data["previsions"][0]
    niveau_pred = pred.get("niveau") or 1
    delta = niveau_observe - niveau_pred  # >0 = sous-estimé ; <0 = sur-estimé

    poids = _charger_poids()
    if delta != 0:
        # Identifie le facteur qui dominait dans la prédiction
        facteurs = pred.get("facteurs", {})
        if facteurs:
            facteur_dominant = max(
                (k for k, v in facteurs.items() if v.get("disponible")),
                key=lambda k: (facteurs[k].get("valeur") or 0) * facteurs[k].get("poids_applique", 0),
                default=None,
            )
            if facteur_dominant:
                ajustement = 0.02 * delta  # 2 % par niveau d'écart
                poids[facteur_dominant] = max(0.05, min(0.7, poids[facteur_dominant] + ajustement))
                # Renormaliser pour que la somme reste à 1
                somme = sum(poids.values())
                poids = {k: round(v / somme, 4) for k, v in poids.items()}

    # Enregistrement du fichier de calibration
    cal = charger_json(FICHIER_CALIBRATION) or {"observations": [], "poids": {}}
    cal["observations"].append({
        "site_id": site_id,
        "date": date_obs.isoformat(),
        "niveau_predit": niveau_pred,
        "niveau_observe": niveau_observe,
        "delta": delta,
    })
    cal["poids"] = poids
    cal["derniere_maj"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    enregistrer_json(FICHIER_CALIBRATION, cal)

    logger.info(
        "Calibration enregistrée pour %s (%s) : niveau prédit %d, observé %d → poids %s",
        site_id, date_obs, niveau_pred, niveau_observe, poids,
    )
    return poids


if __name__ == "__main__":
    # Mode CLI : python src/compute_risk.py [calibrate site_id YYYY-MM-DD niveau]
    import sys

    if len(sys.argv) >= 5 and sys.argv[1] == "calibrate":
        site_id = sys.argv[2]
        date_obs = date.fromisoformat(sys.argv[3])
        niveau = int(sys.argv[4])
        nouveaux_poids = calibrate(site_id, date_obs, niveau)
        print("Nouveaux poids :", nouveaux_poids)
    else:
        print("Usage : python compute_risk.py calibrate <site_id> <YYYY-MM-DD> <niveau>")
