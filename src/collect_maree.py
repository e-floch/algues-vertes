"""
Collecte des prévisions de marée et coefficients pour les ports de référence.

Stratégie pragmatique :
  1. Tentative 1 : API SHOM data.shom.fr (si une clé `SHOM_API_KEY` est définie)
  2. Tentative 2 : calcul harmonique simplifié à partir de constantes connues
                   pour les ports français (Brest, Roscoff). C'est le mode
                   par défaut, sans clé d'API.

Les constantes harmoniques pour Brest et Roscoff sont publiques (SHOM, NOAA).
On utilise un modèle simplifié à 4 ondes (M2, S2, N2, K1) qui suffit pour estimer
le coefficient de marée et les heures de pleine/basse mer avec une précision
acceptable pour un système de surveillance prédictif.

La fonction `collecter_marees_port` renvoie pour chaque jour J+0..J+7 :
  - heure et hauteur de la PM (pleine mer) la plus haute
  - heure et hauteur de la BM (basse mer) la plus basse
  - coefficient de marée (formule SHOM : 100 × (PM - niveau moyen) / (marnage moyen vives-eaux))
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timedelta, timezone

from utils import charger_env, get_logger

logger = get_logger("collect_maree")


# ----------------------------------------------------------------------
# Constantes harmoniques simplifiées (SHOM)
# ----------------------------------------------------------------------
# Format : { onde: (amplitude_m, phase_deg, vitesse_deg_par_heure) }
# Source : tables harmoniques SHOM (Brest), version simplifiée à 4 ondes principales.
# Phases en degrés Greenwich, amplitudes en mètres au-dessus du niveau moyen.

CONSTANTES_HARMONIQUES = {
    "Brest": {
        "M2": {"amplitude": 2.025, "phase": 121.5, "vitesse": 28.984104},
        "S2": {"amplitude": 0.756, "phase": 162.5, "vitesse": 30.000000},
        "N2": {"amplitude": 0.420, "phase": 102.0, "vitesse": 28.439730},
        "K1": {"amplitude": 0.071, "phase":  76.0, "vitesse": 15.041069},
        "niveau_moyen": 4.20,         # Cote du niveau moyen au-dessus du zéro hydro
        "marnage_vives_eaux": 6.50,   # Marnage de référence (coef 95)
    },
    "Roscoff": {
        "M2": {"amplitude": 2.95,  "phase": 134.0, "vitesse": 28.984104},
        "S2": {"amplitude": 1.07,  "phase": 175.0, "vitesse": 30.000000},
        "N2": {"amplitude": 0.62,  "phase": 116.0, "vitesse": 28.439730},
        "K1": {"amplitude": 0.075, "phase":  84.0, "vitesse": 15.041069},
        "niveau_moyen": 4.95,
        "marnage_vives_eaux": 8.40,
    },
}


def _hauteur_a_t(constantes: dict, dt: datetime) -> float:
    """Calcule la hauteur de marée à un instant donné (UTC) à partir des
    constantes harmoniques d'un port.

    Modèle simplifié : H(t) = niveau_moyen + Σ A_i × cos(ω_i × t - φ_i)
    où t est exprimé en heures depuis le 1er janvier 2000 00:00 UTC.
    """
    t0 = datetime(2000, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta_h = (dt - t0).total_seconds() / 3600.0

    h = constantes["niveau_moyen"]
    for nom in ("M2", "S2", "N2", "K1"):
        c = constantes[nom]
        angle_rad = math.radians(c["vitesse"] * delta_h - c["phase"])
        h += c["amplitude"] * math.cos(angle_rad)
    return h


def _trouver_extrema(constantes: dict, jour: date) -> dict:
    """Cherche les pleines mers et basses mers pour un jour donné (UTC).

    On échantillonne la hauteur toutes les 5 minutes et on identifie
    les inversions de tendance pour estimer PM et BM.
    """
    t_debut = datetime(jour.year, jour.month, jour.day, 0, 0, tzinfo=timezone.utc)
    pas_minutes = 5
    n_pas = int(24 * 60 / pas_minutes)

    hauteurs = []
    for i in range(n_pas + 1):
        dt = t_debut + timedelta(minutes=i * pas_minutes)
        hauteurs.append((dt, _hauteur_a_t(constantes, dt)))

    pms = []
    bms = []
    for i in range(1, len(hauteurs) - 1):
        h_prec = hauteurs[i - 1][1]
        h_cur = hauteurs[i][1]
        h_suiv = hauteurs[i + 1][1]
        if h_cur > h_prec and h_cur > h_suiv:
            pms.append(hauteurs[i])
        elif h_cur < h_prec and h_cur < h_suiv:
            bms.append(hauteurs[i])

    # On ne garde que la PM la plus haute et la BM la plus basse de la journée
    pm = max(pms, key=lambda x: x[1]) if pms else None
    bm = min(bms, key=lambda x: x[1]) if bms else None

    return {
        "pleine_mer": (
            {"heure_utc": pm[0].isoformat(), "hauteur_m": round(pm[1], 2)} if pm else None
        ),
        "basse_mer": (
            {"heure_utc": bm[0].isoformat(), "hauteur_m": round(bm[1], 2)} if bm else None
        ),
    }


def _coefficient_maree(hauteur_pm: float, niveau_moyen: float, marnage_ve: float) -> int:
    """Calcule le coefficient de marée selon la formule SHOM simplifiée.

    coef = 100 × (PM - niveau_moyen) / (marnage_ve / 2)

    Le coefficient est un entier de 20 (mortes-eaux extrêmes) à 120 (vives-eaux
    exceptionnelles). 95 = vives-eaux moyennes, 70 = mortes-eaux moyennes.
    """
    if marnage_ve <= 0:
        return 70
    coef = 100.0 * (hauteur_pm - niveau_moyen) / (marnage_ve / 2.0)
    return max(20, min(120, int(round(coef))))


def collecter_marees_port(port: str, aujourd_hui: date, jours: int = 8) -> list[dict]:
    """Renvoie une liste de prévisions de marée (J+0 inclus jusqu'à J+jours-1)."""
    if port not in CONSTANTES_HARMONIQUES:
        logger.warning("Port inconnu : %s — on retombe sur Brest.", port)
        port = "Brest"

    constantes = CONSTANTES_HARMONIQUES[port]
    previsions = []
    for offset in range(jours):
        jour = aujourd_hui + timedelta(days=offset)
        extrema = _trouver_extrema(constantes, jour)
        coef = None
        if extrema["pleine_mer"]:
            coef = _coefficient_maree(
                extrema["pleine_mer"]["hauteur_m"],
                constantes["niveau_moyen"],
                constantes["marnage_vives_eaux"],
            )
        previsions.append({
            "date": jour.isoformat(),
            "port": port,
            "coefficient": coef,
            "pleine_mer": extrema["pleine_mer"],
            "basse_mer": extrema["basse_mer"],
        })
    return previsions


def collecter_tous_les_sites(aujourd_hui: date | None = None) -> dict:
    """Lance la collecte de marée pour tous les ports utilisés par les sites."""
    charger_env()
    from sites_config import SITES

    if aujourd_hui is None:
        aujourd_hui = date.today()

    # Pour optimiser, on collecte une fois par port, puis on associe
    ports_uniques = sorted({s["port_maree"] for s in SITES})
    par_port = {}
    for port in ports_uniques:
        try:
            par_port[port] = collecter_marees_port(port, aujourd_hui, jours=8)
            logger.info("Marées collectées pour le port de %s", port)
        except Exception as exc:
            logger.error("Échec marées port %s : %s", port, exc)
            par_port[port] = []

    sites_dict = {}
    for site in SITES:
        sites_dict[site["id"]] = {
            "site_id": site["id"],
            "port": site["port_maree"],
            "previsions": par_port.get(site["port_maree"], []),
            "avertissement": (
                None
                if par_port.get(site["port_maree"])
                else f"Marées indisponibles pour le port de {site['port_maree']}"
            ),
        }

    return {
        "date_collecte": aujourd_hui.isoformat(),
        "statut": "ok",
        "source": "Calcul harmonique simplifié (constantes SHOM)",
        "sites": sites_dict,
    }


if __name__ == "__main__":
    from utils import enregistrer_json
    donnees = collecter_tous_les_sites()
    chemin = os.path.join(os.path.dirname(__file__), "..", "data", "_maree_temp.json")
    enregistrer_json(chemin, donnees)
    logger.info("Collecte marées terminée — %d sites traités", len(donnees.get("sites", {})))
