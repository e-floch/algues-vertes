"""
Diagnostic Sentinel-2 — à lancer depuis le terminal :

    cd chemin/vers/algues-vertes
    python diagnostic_sentinel.py

Teste deux hypothèses sur l'absence d'images :
  H1 — Nuages : aucune image avec sampleCount > 0 sur 14 jours
  H2 — Filtre SCL trop strict : le FAI exige SCL=6 (eau) mais les pixels
       eau sont classés SCL=5 (eau peu profonde) → sampleCount = 0
       même par ciel clair
"""
import os
import sys
from datetime import date, timedelta

import requests

# ── Chargement .env ────────────────────────────────────────────────────────────
from pathlib import Path
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

CDSE_CLIENT_ID     = os.environ.get("CDSE_CLIENT_ID", "")
CDSE_CLIENT_SECRET = os.environ.get("CDSE_CLIENT_SECRET", "")

if not CDSE_CLIENT_ID or not CDSE_CLIENT_SECRET:
    sys.exit("ERREUR : CDSE_CLIENT_ID / CDSE_CLIENT_SECRET absents du .env")

# ── Authentification ───────────────────────────────────────────────────────────
print("1. Authentification CDSE...")
rep = requests.post(
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
    data={
        "grant_type": "client_credentials",
        "client_id": CDSE_CLIENT_ID,
        "client_secret": CDSE_CLIENT_SECRET,
    },
    timeout=20,
)
rep.raise_for_status()
token = rep.json()["access_token"]
print("   ✓ Token obtenu\n")

# ── Zone de test : baie de Douarnenez (site représentatif) ─────────────────────
# bbox zone 2 pélagique 30×30 km centrée sur Douarnenez
BBOX = [-4.56, 47.97, -4.06, 48.31]   # [min_lon, min_lat, max_lon, max_lat]
STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

aujourd_hui = date.today()
date_debut  = aujourd_hui - timedelta(days=14)
date_fin    = aujourd_hui

# ── Evalscripts ────────────────────────────────────────────────────────────────
# H1 / H2a : FAI avec filtre strict SCL=6 (code actuel)
EVALSCRIPT_FAI_STRICT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "B11", "SCL"] }],
    output: [{ id: "default", bands: 1, sampleType: "FLOAT32" }, { id: "dataMask", bands: 1 }]
  };
}
function evaluatePixel(s) {
  if (s.SCL !== 6) { return { default: [NaN], dataMask: [0] }; }
  let baseline = s.B04 + (s.B11 - s.B04) * (842.0 - 665.0) / (1610.0 - 665.0);
  return { default: [s.B08 - baseline], dataMask: [1] };
}
"""

# H2b : FAI avec filtre élargi SCL=5 (eau peu profonde) + SCL=6
EVALSCRIPT_FAI_LARGE = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "B11", "SCL"] }],
    output: [{ id: "default", bands: 1, sampleType: "FLOAT32" }, { id: "dataMask", bands: 1 }]
  };
}
function evaluatePixel(s) {
  // SCL 5 = eau peu profonde/turbide, SCL 6 = eau
  if (s.SCL !== 5 && s.SCL !== 6) { return { default: [NaN], dataMask: [0] }; }
  // Exclure nuages et ombres explicitement
  if (s.SCL === 3 || s.SCL === 8 || s.SCL === 9 || s.SCL === 10) {
    return { default: [NaN], dataMask: [0] };
  }
  let baseline = s.B04 + (s.B11 - s.B04) * (842.0 - 665.0) / (1610.0 - 665.0);
  return { default: [s.B08 - baseline], dataMask: [1] };
}
"""

# H3 : NDVI sans masque SCL du tout (juste nuages exclus) — vérifie si l'image existe
EVALSCRIPT_NDVI_MINIMAL = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL"] }],
    output: [{ id: "default", bands: 1, sampleType: "FLOAT32" }, { id: "dataMask", bands: 1 }]
  };
}
function evaluatePixel(s) {
  // Uniquement nuages/ombres masqués — tout le reste accepté
  if (s.SCL === 3 || s.SCL === 8 || s.SCL === 9 || s.SCL === 10) {
    return { default: [NaN], dataMask: [0] };
  }
  let denom = s.B08 + s.B04;
  let ndvi = (denom === 0) ? 0 : (s.B08 - s.B04) / denom;
  return { default: [ndvi], dataMask: [1] };
}
"""


def appeler_stats(evalscript: str, label: str):
    """Appelle la Statistics API et affiche les résultats par jour."""
    payload = {
        "input": {
            "bounds": {
                "bbox": BBOX,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": f"{date_debut.isoformat()}T00:00:00Z",
                        "to":   f"{date_fin.isoformat()}T23:59:59Z",
                    },
                    "maxCloudCoverage": 80,
                    "mosaickingOrder": "mostRecent",
                },
            }],
        },
        "aggregation": {
            "timeRange": {
                "from": f"{date_debut.isoformat()}T00:00:00Z",
                "to":   f"{date_fin.isoformat()}T23:59:59Z",
            },
            "aggregationInterval": {"of": "P1D"},
            "evalscript": evalscript,
            "resx": 0.0002,
            "resy": 0.0002,
        },
        "calculations": {
            "default": {"statistics": {"default": {"percentiles": {"k": [50]}}}}
        },
    }

    rep = requests.post(
        STATS_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=60,
    )

    print(f"\n── {label} ──")
    if rep.status_code != 200:
        print(f"   ERREUR HTTP {rep.status_code} : {rep.text[:300]}")
        return

    data = rep.json().get("data", [])
    images_valides = 0
    for it in sorted(data, key=lambda d: d.get("interval", {}).get("from", "")):
        date_img = it.get("interval", {}).get("from", "")[:10]
        outputs  = it.get("outputs", {}).get("default", {}).get("bands", {})
        nom_bande = next(iter(outputs), None)
        if not nom_bande:
            continue
        stats = outputs[nom_bande].get("stats", {})
        sample  = stats.get("sampleCount", 0)
        nodata  = stats.get("noDataCount", 0)
        mean    = stats.get("mean")
        if sample > 0:
            images_valides += 1
            print(f"   {date_img}  ✓  sampleCount={sample:6d}  noData={nodata:6d}  mean={mean:.4f}")
        else:
            print(f"   {date_img}  ✗  sampleCount=0  (100% masqué)")

    if images_valides == 0:
        print("   → AUCUNE image valide sur 14 jours avec ce filtre")
    else:
        print(f"   → {images_valides} image(s) valide(s) trouvée(s)")


# ── Tests ──────────────────────────────────────────────────────────────────────
print(f"Fenêtre : {date_debut} → {date_fin}")
print(f"Zone    : bbox {BBOX} (Douarnenez, zone pélagique ~30×30 km)\n")

appeler_stats(EVALSCRIPT_FAI_STRICT,   "H1+H2a : FAI filtre STRICT (SCL=6 uniquement) — code actuel")
appeler_stats(EVALSCRIPT_FAI_LARGE,    "H2b    : FAI filtre ÉLARGI (SCL=5 + SCL=6)")
appeler_stats(EVALSCRIPT_NDVI_MINIMAL, "H3     : NDVI filtre MINIMAL (nuages seuls exclus)")

print("\n── INTERPRÉTATION ──")
print("H3 aucune image → nuages sur toute la fenêtre (météo)")
print("H3 a des images mais H1 non → filtre SCL=6 trop strict (bug)")
print("H2b a des images mais H1 non → SCL=5 manquant (eaux turbides/côtières)")
