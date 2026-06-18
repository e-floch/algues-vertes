"""
Générateur du tableau de bord HTML.

Le fichier produit est `docs/index.html`. Il s'agit d'une page statique unique
chargeant Leaflet via CDN. Toutes les données sont chargées dynamiquement
en JavaScript depuis `docs/data/<YYYY-MM-DD>.json` (copiés depuis `data/`).

Le script copie aussi les fichiers JSON quotidiens dans `docs/data/` afin
qu'ils soient servis par Netlify, et génère un `docs/data/manifest.json`
qui liste les dates disponibles.
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from utils import (
    DOSSIER_DATA,
    DOSSIER_DOCS,
    DOSSIER_DOCS_DATA,
    charger_json,
    enregistrer_json,
    get_logger,
)

logger = get_logger("generate_dashboard")


def synchroniser_donnees() -> list[str]:
    """Copie tous les JSON de data/ vers docs/data/ et renvoie la liste
    des dates disponibles (ordonnées du plus récent au plus ancien)."""
    DOSSIER_DOCS_DATA.mkdir(parents=True, exist_ok=True)

    dates_disponibles = []
    for fichier in DOSSIER_DATA.glob("*.json"):
        try:
            d = date.fromisoformat(fichier.stem)
        except ValueError:
            continue  # On ignore les fichiers temporaires (commençant par "_")
        cible = DOSSIER_DOCS_DATA / fichier.name
        # Copie systématique pour s'assurer que la version la plus récente est servie
        shutil.copy2(fichier, cible)
        dates_disponibles.append(d.isoformat())

    dates_disponibles.sort(reverse=True)

    # Manifest = liste des dates disponibles + date la plus récente
    manifest = {
        "dates": dates_disponibles,
        "derniere_date": dates_disponibles[0] if dates_disponibles else None,
    }
    enregistrer_json(DOSSIER_DOCS_DATA / "manifest.json", manifest)
    logger.info("Manifest mis à jour : %d dates disponibles", len(dates_disponibles))
    return dates_disponibles


# ----------------------------------------------------------------------
# Gabarit HTML
# ----------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Surveillance algues vertes — Bretagne</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <style>
    :root {
      --bg: #f7f8fa;
      --bg-panel: #ffffff;
      --texte: #2c3e50;
      --texte-faible: #7f8c8d;
      --bord: #e1e4e8;
      --niveau-1: #3CB371;
      --niveau-2: #F1C40F;
      --niveau-3: #E67E22;
      --niveau-4: #C0392B;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--texte);
      font-size: 14px;
      line-height: 1.5;
    }
    header {
      background: var(--bg-panel);
      border-bottom: 1px solid var(--bord);
      padding: 14px 20px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 16px;
    }
    header h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 600;
    }
    header .meta {
      color: var(--texte-faible);
      font-size: 13px;
      flex-grow: 1;
    }
    header label {
      font-size: 13px;
      color: var(--texte-faible);
    }
    header select {
      padding: 6px 10px;
      border: 1px solid var(--bord);
      border-radius: 4px;
      background: white;
      font-size: 13px;
    }
    .alerts-globales {
      background: #fff3cd;
      border-bottom: 1px solid #ffeeba;
      padding: 10px 20px;
      color: #856404;
      font-size: 13px;
    }
    .alerts-globales:empty { display: none; }
    main {
      display: flex;
      height: calc(100vh - 60px);
      min-height: 500px;
    }
    @media (max-width: 768px) {
      main { flex-direction: column; height: auto; }
      #carte { height: 50vh; }
      #panneau { width: 100% !important; height: auto !important; max-height: none !important; }
    }
    #carte {
      width: 38%;
      min-width: 280px;
      min-height: 400px;
      flex-shrink: 0;
    }
    #panneau {
      flex: 1;
      min-width: 0;
      background: var(--bg-panel);
      border-left: 1px solid var(--bord);
      overflow-y: auto;
      padding: 16px 20px;
    }
    #panneau h2 {
      margin: 0 0 4px 0;
      font-size: 16px;
    }
    #panneau .baie {
      color: var(--texte-faible);
      font-size: 13px;
      margin-bottom: 16px;
    }
    .section {
      margin-bottom: 22px;
    }
    .section h3 {
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--texte-faible);
      margin: 0 0 8px 0;
      font-weight: 600;
    }
    /* Grille J+1→J+7 en 7 colonnes */
    .previsions-grille {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      gap: 5px;
      margin-bottom: 4px;
    }
    .prev-carte {
      border-radius: 5px;
      padding: 8px 4px;
      text-align: center;
      color: white;
      font-size: 11px;
      line-height: 1.4;
      cursor: default;
    }
    .prev-carte .prev-horizon {
      font-weight: 700;
      font-size: 12px;
    }
    .prev-carte .prev-nom {
      opacity: 0.92;
      font-size: 10px;
    }
    .prev-carte .prev-score {
      opacity: 0.85;
      font-size: 10px;
      margin-top: 2px;
    }
    .niveau-2 .prev-carte, .niveau-2 { color: #5a4500; }
    .niveau-1 { background-color: var(--niveau-1); }
    .niveau-2 { background-color: var(--niveau-2); color: #5a4500 !important; }
    .niveau-3 { background-color: var(--niveau-3); }
    .niveau-4 { background-color: var(--niveau-4); }
    .niveau-indispo { background-color: #95a5a6; }
    .facteurs-table {
      width: 100%;
      font-size: 12px;
      border-collapse: collapse;
    }
    .facteurs-table th, .facteurs-table td {
      padding: 4px 6px;
      text-align: left;
      border-bottom: 1px solid var(--bord);
    }
    .facteurs-table th {
      color: var(--texte-faible);
      font-weight: 500;
      text-transform: uppercase;
      font-size: 11px;
    }
    .facteurs-table td.dispo-non {
      color: var(--texte-faible);
      font-style: italic;
    }
    .avert {
      background: #fdf3e3;
      border-left: 3px solid #f39c12;
      padding: 8px 12px;
      font-size: 12px;
      color: #8a5e0a;
      margin-top: 8px;
      border-radius: 0 3px 3px 0;
    }
    .placeholder {
      color: var(--texte-faible);
      text-align: center;
      padding: 40px 20px;
      font-size: 14px;
    }
    /* Marqueurs Leaflet personnalisés */
    .marker-niveau {
      width: 26px;
      height: 26px;
      border-radius: 50%;
      border: 3px solid white;
      box-shadow: 0 2px 4px rgba(0,0,0,0.3);
      display: block;
    }
    .legende {
      position: absolute;
      bottom: 20px;
      left: 20px;
      background: white;
      padding: 12px 14px;
      border: 1px solid var(--bord);
      border-radius: 4px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.1);
      font-size: 12px;
      z-index: 500;
    }
    .legende-item {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 3px 0;
    }
    .legende-puce {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 2px solid white;
      box-shadow: 0 1px 2px rgba(0,0,0,0.2);
    }
    /* Bandeau H2S */
    .h2s-bandeau {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 14px;
      border-radius: 4px;
      color: white;
      margin-bottom: 8px;
    }
    .h2s-bandeau .h2s-val {
      font-size: 22px;
      font-weight: 600;
    }
    .h2s-bandeau .h2s-val span {
      font-size: 13px;
      font-weight: 400;
      opacity: 0.9;
    }
    .h2s-bandeau .h2s-niveau {
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: 0.04em;
    }
    /* Graphique SVG simple */
    .graph-svg {
      width: 100%;
      height: 140px;
      display: block;
      background: #fafbfc;
      border: 1px solid var(--bord);
      border-radius: 4px;
    }
    .graph-axis {
      stroke: #c8cdd2;
      stroke-width: 1;
    }
    .graph-line {
      fill: none;
      stroke: #2980b9;
      stroke-width: 2;
    }
    .graph-area {
      fill: rgba(41, 128, 185, 0.15);
    }
    .graph-label {
      font-size: 10px;
      fill: var(--texte-faible);
    }
  </style>
</head>
<body>
  <header>
    <h1>Surveillance algues vertes — Bretagne</h1>
    <div class="meta" id="meta-maj">Chargement...</div>
    <label for="date-select">Consulter une date :</label>
    <select id="date-select"></select>
  </header>
  <div class="alerts-globales" id="alerts-globales"></div>
  <main>
    <div id="carte"></div>
    <aside id="panneau">
      <div class="placeholder">Cliquez sur un marqueur de la carte pour afficher le détail d'un site.</div>
    </aside>
  </main>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
          integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <script>
  (function() {
    "use strict";

    // ----- Constantes -----
    const NIVEAU_COULEURS = {
      1: "#3CB371",
      2: "#F1C40F",
      3: "#E67E22",
      4: "#C0392B",
    };
    const NIVEAU_NOMS = {
      1: "Veille",
      2: "Vigilance",
      3: "Alerte",
      4: "Critique",
    };

    // ----- État -----
    let carte;
    let marqueurs = [];
    let manifest = null;
    let donneesActuelles = null;
    let siteSelectionne = null;

    // ----- Carte Leaflet -----
    function initCarte() {
      carte = L.map("carte", {
        center: [48.5, -4.0],
        zoom: 9,
        zoomControl: true,
      });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(carte);
      ajouterLegende();
    }

    function ajouterLegende() {
      const legende = L.control({ position: "bottomleft" });
      legende.onAdd = function() {
        const div = L.DomUtil.create("div", "legende");
        let html = "<strong>Niveaux d'alerte (J+1)</strong>";
        for (const [n, nom] of Object.entries(NIVEAU_NOMS)) {
          html += `<div class="legende-item"><span class="legende-puce" style="background:${NIVEAU_COULEURS[n]}"></span>${n} — ${nom}</div>`;
        }
        div.innerHTML = html;
        return div;
      };
      legende.addTo(carte);
    }

    function effacerMarqueurs() {
      marqueurs.forEach(m => carte.removeLayer(m));
      marqueurs = [];
    }

    function afficherMarqueurs(donnees) {
      effacerMarqueurs();
      donnees.sites.forEach(site => {
        const niv = site.previsions.length > 0 ? site.previsions[0].niveau : null;
        const couleur = niv ? NIVEAU_COULEURS[niv] : "#888888";
        const icone = L.divIcon({
          className: "",
          html: `<span class="marker-niveau" style="background:${couleur}"></span>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        });
        const marker = L.marker([site.lat, site.lon], { icon: icone })
          .bindTooltip(site.site_nom, { interactive: true })
          .on("click", () => afficherDetailSite(site));
        marker.addTo(carte);
        marqueurs.push(marker);
        // Rendre le tooltip cliquable (évite que cliquer sur le label ne fasse rien)
        marker.on("tooltipopen", function(e) {
          const el = e.tooltip.getElement();
          if (el && !el._clickAdded) {
            el.style.cursor = "pointer";
            L.DomEvent.on(el, "click", () => afficherDetailSite(site));
            el._clickAdded = true;
          }
        });
      });
      // Recadrer la carte pour que tous les marqueurs soient visibles avec une marge
      if (marqueurs.length > 0) {
        carte.fitBounds(L.featureGroup(marqueurs).getBounds(), { padding: [40, 40] });
      }
    }

    // ----- Panneau de détail -----
    function afficherDetailSite(site) {
      siteSelectionne = site.site_id;
      const panneau = document.getElementById("panneau");

      let html = `
        <h2>${escapeHtml(site.site_nom)}</h2>
        <div class="baie">${escapeHtml(site.baie)}${site.year_round ? " · surveillance toute l'année" : ""}</div>
      `;

      // Niveaux J+1 → J+7 — grille 7 colonnes
      html += `<div class="section"><h3>Prévision J+1 → J+7</h3><div class="previsions-grille">`;
      site.previsions.forEach(p => {
        const cls = p.niveau ? `niveau-${p.niveau}` : "niveau-indispo";
        const score = p.score !== null && p.score !== undefined
          ? `${p.score.toFixed(0)}/100`
          : "—";
        const nomCourt = (p.nom_niveau || "").replace("Vigilance", "Vigil.").replace("Critique", "Crit.");
        html += `
          <div class="prev-carte ${cls}">
            <div class="prev-horizon">${escapeHtml(p.horizon)}</div>
            <div class="prev-nom">${escapeHtml(nomCourt)}</div>
            <div class="prev-score">${score}</div>
          </div>`;
      });
      html += `</div></div>`;

      // Détail des facteurs (J+1) avec zone de référence
      const j1 = site.previsions[0];
      if (j1 && j1.facteurs) {
        html += `<div class="section"><h3>Détail des facteurs (J+1)</h3>
          <table class="facteurs-table">
            <tr><th>Facteur</th><th>Valeur</th><th>Poids</th><th style="font-size:10px;color:var(--texte-faible)">Zone de référence</th></tr>`;
        const meta = {
          fai_zone_2:  { label: "Masse algale (FAI zone 2)", zone: "Zone pélagique ~30 km · Sentinel-2 · p75" },
          vent:        { label: "Vent",                      zone: "Prévision météo J+1→J+7 · Open-Meteo" },
          coef_maree:  { label: "Coefficient marée",         zone: "Port de référence · SHOM" },
          ndvi_zone_1: { label: "Biomasse côtière (NDVI)",   zone: "Zone côtière ~6 km · Sentinel-2 · moyenne" },
        };
        for (const [k, m] of Object.entries(meta)) {
          const f = j1.facteurs[k] || {};
          if (f.disponible) {
            html += `<tr><td>${m.label}</td><td>${(f.valeur ?? "—").toString()}</td><td>${(f.poids_applique * 100).toFixed(0)} %</td><td style="font-size:10px;color:var(--texte-faible)">${m.zone}</td></tr>`;
          } else {
            html += `<tr class="dispo-non"><td>${m.label}</td><td colspan="3">indisponible</td></tr>`;
          }
        }
        html += `</table></div>`;
      }

      // Données Sentinel-2 — deux images : zone côtière (NDVI) et pélagique (FAI)
      if (site.sentinel) {
        html += `<div class="section"><h3>Sentinel-2</h3>`;
        const dateImg = site.sentinel.image_la_plus_recente || "—";
        const imgNonExpl = site.sentinel.image_non_exploitee; // {date_image, nuage_pct} ou null

        // Estimation couverture nuageuse depuis fai_zone_2 (noDataCount / total)
        const faiRaw = site.sentinel.fai_zone_2;
        let badgeNuage = "";
        if (faiRaw && (faiRaw.sampleCount != null) && (faiRaw.noDataCount != null)) {
          const total = faiRaw.sampleCount + faiRaw.noDataCount;
          const nuagePct = total > 0 ? Math.round(faiRaw.noDataCount / total * 100) : null;
          if (nuagePct !== null) {
            let coulNuage, labelNuage;
            if (nuagePct >= 70) {
              coulNuage = "#c0392b"; labelNuage = `Inutilisable — ${nuagePct}% nuages`;
            } else if (nuagePct >= 30) {
              coulNuage = "#e67e22"; labelNuage = `Partiellement nuageux — ${nuagePct}% nuages`;
            } else {
              coulNuage = "#27ae60"; labelNuage = `Utilisable — ${nuagePct}% nuages`;
            }
            badgeNuage = `<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:${coulNuage};color:#fff;font-size:11px;font-weight:600;margin-left:8px">${labelNuage}</span>`;
          }
        }

        if (imgNonExpl && imgNonExpl.date_image) {
          // Une image plus récente existe mais n'a pas été exploitée (trop nuageuse)
          html += `<div style="font-size:12px;color:var(--texte-faible);margin-bottom:4px">
            Image disponible : <strong style="color:#e67e22">${imgNonExpl.date_image}</strong>
            <span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#e67e22;color:#fff;font-size:11px;font-weight:600;margin-left:6px">non exploitée — ${imgNonExpl.nuage_pct}% nuages</span>
          </div>
          <div style="font-size:12px;color:var(--texte-faible);margin-bottom:8px">
            Statistiques FAI basées sur : <strong style="color:var(--texte)">${dateImg}</strong>${badgeNuage}
          </div>`;
        } else if (site.sentinel.est_fallback) {
          html += `<div style="font-size:12px;color:var(--texte-faible);margin-bottom:8px">
            Dernière image disponible : <strong style="color:var(--texte)">${dateImg}</strong>
            <span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#7f8c8d;color:#fff;font-size:11px;font-weight:600;margin-left:6px">crédits CDSE épuisés — image non actualisée</span>
          </div>`;
        } else {
          html += `<div style="font-size:12px;color:var(--texte-faible);margin-bottom:8px">
            Dernière image : <strong style="color:var(--texte)">${dateImg}</strong>${badgeNuage}
          </div>`;
        }

        const legende = `<span style="color:#00dc32;font-weight:600">■</span> algues flottantes · ${dateImg}`;

        // Deux images côte à côte : pélagique (FAI) + côtière (NDVI)
        html += `<div style="display:flex;gap:10px;flex-wrap:wrap">`;

        if (site.sentinel.image_miniature_pelagique) {
          const fai = site.sentinel.fai_zone_2;
          const faiVal = fai ? (fai.percentile_75 ?? fai.percentile_50 ?? fai.mean) : null;
          const faiTxt = faiVal !== null ? `FAI p75 = ${faiVal.toFixed(4)}` : "";
          html += `
            <div style="flex:1;min-width:140px">
              <div style="font-size:11px;font-weight:600;margin-bottom:3px;color:var(--texte)">
                Zone pélagique (~30 km) — FAI
              </div>
              <img src="${site.sentinel.image_miniature_pelagique}"
                   alt="Zone pélagique Sentinel-2"
                   style="width:100%;border-radius:6px;border:2px solid #1a73e8;display:block">
              <div style="font-size:10px;color:var(--texte-faible);margin-top:3px">${legende}<br>${faiTxt}</div>
            </div>`;
        }

        if (site.sentinel.image_miniature) {
          const ndvi = site.sentinel.ndvi_zone_1;
          const ndviVal = ndvi ? ndvi.mean : null;
          const ndviTxt = ndviVal !== null ? `NDVI moy = ${ndviVal.toFixed(3)}` : "";
          html += `
            <div style="flex:1;min-width:140px">
              <div style="font-size:11px;font-weight:600;margin-bottom:3px;color:var(--texte)">
                Zone côtière (~6 km) — NDVI
              </div>
              <img src="${site.sentinel.image_miniature}"
                   alt="Zone côtière Sentinel-2"
                   style="width:100%;border-radius:6px;border:2px solid #2ecc71;display:block">
              <div style="font-size:10px;color:var(--texte-faible);margin-top:3px">${legende}<br>${ndviTxt}</div>
            </div>`;
        }

        html += `</div>`;

        if (!site.sentinel.image_miniature_pelagique && !site.sentinel.image_miniature && site.sentinel.image_la_plus_recente) {
          html += `<div>Image la plus récente : <strong>${site.sentinel.image_la_plus_recente}</strong></div>`;
        }

        if (site.sentinel.avertissement) {
          html += `<div class="avert">${escapeHtml(site.sentinel.avertissement)}</div>`;
        }
        html += `</div>`;
      }

      // Qualité de l'air — H2S (AirBreizh)
      if (site.airbreizh) {
        html += `<div class="section"><h3>Qualité de l'air — H2S (AirBreizh)</h3>`;
        const ab = site.airbreizh;
        if (ab.mesure && ab.mesure.derniere_mesure_ug_m3 !== null) {
          const m = ab.mesure;
          const couleur = m.couleur || "#888";
          html += `
            <div class="h2s-bandeau" style="background:${couleur}">
              <div class="h2s-val">${m.derniere_mesure_ug_m3} <span>µg/m³</span></div>
              <div class="h2s-niveau">${escapeHtml(m.niveau_sanitaire || "—")}</div>
            </div>
            <table class="facteurs-table">
              <tr><th>Station</th><td>${escapeHtml(ab.station ? ab.station.nom : "—")}${ab.station && ab.station.distance_km ? ` <span style="color:var(--texte-faible);font-size:11px">(${ab.station.distance_km} km)</span>` : ""}</td></tr>
              <tr><th>Dernière mesure</th><td>${m.horodate_derniere_mesure ? new Date(m.horodate_derniere_mesure).toLocaleString("fr-FR", {day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit"}) : "—"}</td></tr>
              <tr><th>Moyenne 24 h</th><td>${m.moyenne_24h_ug_m3 ?? "—"} µg/m³</td></tr>
              <tr><th>Maximum 7 j</th><td>${m.max_7j_ug_m3 ?? "—"} µg/m³</td></tr>
              <tr><th>Nb mesures (7 j)</th><td>${m.nb_mesures_7j ?? "—"}</td></tr>
            </table>
            <div class="avert" style="border-color:${couleur}; background:${couleur}22; color:#444;">
              ${escapeHtml(m.description_seuil || "")}
            </div>`;
        } else {
          html += `<div class="avert">${escapeHtml(ab.raison || "Pas de mesure H2S disponible.")}</div>`;
        }
        html += `</div>`;
      }

      // Vent et marée
      if (site.meteo && site.meteo.previsions && site.meteo.previsions.length) {
        const p = site.meteo.previsions.find(x => x.date === j1.date) || site.meteo.previsions[0];
        if (p) {
          html += `<div class="section"><h3>Vent (${escapeHtml(site.meteo.source || '')})</h3>
            <div>Vent moyen : ${p.vent_moyen_kmh ?? "—"} km/h, max ${p.vent_max_kmh ?? "—"} km/h</div>
            <div>Direction dominante : ${p.direction_dominante_deg ?? "—"}°</div></div>`;
        }
      }
      if (site.maree && site.maree.previsions && site.maree.previsions.length) {
        const p = site.maree.previsions.find(x => x.date === j1.date) || site.maree.previsions[0];
        if (p) {
          html += `<div class="section"><h3>Marée (port de ${escapeHtml(site.maree.port || '')})</h3>
            <div>Coefficient : <strong>${p.coefficient ?? "—"}</strong></div>`;
          if (p.pleine_mer) {
            html += `<div>PM : ${p.pleine_mer.heure_utc.substring(11,16)} UTC, ${p.pleine_mer.hauteur_m} m</div>`;
          }
          if (p.basse_mer) {
            html += `<div>BM : ${p.basse_mer.heure_utc.substring(11,16)} UTC, ${p.basse_mer.hauteur_m} m</div>`;
          }
          html += `</div>`;
        }
      }

      // Graphique d'évolution sur 14 jours
      html += `<div class="section"><h3>Évolution du score (14 derniers jours)</h3>
        <div id="graph-historique"></div></div>`;

      panneau.innerHTML = html;
      chargerGraphHistorique(site.site_id);
    }

    // ----- Graphique d'historique sur 14 jours -----
    async function chargerGraphHistorique(siteId) {
      if (!manifest) return;
      const dateRef = donneesActuelles.date;
      const dateRefObj = new Date(dateRef);
      // On collecte les 14 dates précédentes (dans le manifest) avant ou égales à dateRef
      const datesUtiles = manifest.dates
        .filter(d => d <= dateRef)
        .slice(0, 14)
        .reverse();

      const points = [];
      for (const d of datesUtiles) {
        try {
          const r = await fetch(`data/${d}.json`);
          if (!r.ok) continue;
          const j = await r.json();
          const s = (j.sites || []).find(x => x.site_id === siteId);
          if (s && s.previsions && s.previsions[0]) {
            points.push({ date: d, score: s.previsions[0].score });
          }
        } catch (e) { /* ignore */ }
      }
      const cible = document.getElementById("graph-historique");
      if (!cible) return;
      if (points.length === 0) {
        cible.innerHTML = '<div style="color:#7f8c8d;font-size:12px;">Pas d\'historique disponible.</div>';
        return;
      }
      cible.innerHTML = construireSvgGraph(points);
    }

    function construireSvgGraph(points) {
      const W = 380, H = 140;
      const ml = 30, mr = 8, mt = 10, mb = 22;
      const innerW = W - ml - mr;
      const innerH = H - mt - mb;
      const xs = points.map((p, i) => ml + (innerW * i / Math.max(1, points.length - 1)));
      const ys = points.map(p => {
        const v = p.score == null ? 0 : p.score;
        return mt + innerH - (innerH * v / 100);
      });
      let pathLine = "";
      let pathArea = `M ${xs[0]} ${mt + innerH}`;
      for (let i = 0; i < points.length; i++) {
        pathLine += (i === 0 ? "M" : "L") + " " + xs[i] + " " + ys[i] + " ";
        pathArea += " L " + xs[i] + " " + ys[i];
      }
      pathArea += ` L ${xs[xs.length-1]} ${mt + innerH} Z`;

      // Labels axe X (premier, milieu, dernier)
      const labelsX = [];
      const indices = [0, Math.floor(points.length/2), points.length - 1];
      for (const i of indices) {
        if (points[i]) {
          labelsX.push(`<text class="graph-label" x="${xs[i]}" y="${H-6}" text-anchor="middle">${points[i].date.substring(5)}</text>`);
        }
      }

      return `<svg class="graph-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <line class="graph-axis" x1="${ml}" y1="${mt}" x2="${ml}" y2="${mt+innerH}" />
        <line class="graph-axis" x1="${ml}" y1="${mt+innerH}" x2="${W-mr}" y2="${mt+innerH}" />
        <line class="graph-axis" x1="${ml}" y1="${mt+innerH/4}" x2="${W-mr}" y2="${mt+innerH/4}" stroke-dasharray="2,2" />
        <line class="graph-axis" x1="${ml}" y1="${mt+innerH/2}" x2="${W-mr}" y2="${mt+innerH/2}" stroke-dasharray="2,2" />
        <line class="graph-axis" x1="${ml}" y1="${mt+3*innerH/4}" x2="${W-mr}" y2="${mt+3*innerH/4}" stroke-dasharray="2,2" />
        <text class="graph-label" x="${ml-4}" y="${mt+5}" text-anchor="end">100</text>
        <text class="graph-label" x="${ml-4}" y="${mt+innerH/2+3}" text-anchor="end">50</text>
        <text class="graph-label" x="${ml-4}" y="${mt+innerH+4}" text-anchor="end">0</text>
        <path class="graph-area" d="${pathArea}" />
        <path class="graph-line" d="${pathLine}" />
        ${labelsX.join("")}
      </svg>`;
    }

    // ----- Chargement / changement de date -----
    async function chargerDate(dateStr) {
      try {
        const r = await fetch(`data/${dateStr}.json?t=${Date.now()}`);
        if (!r.ok) throw new Error("Fichier introuvable");
        const donnees = await r.json();
        donneesActuelles = donnees;
        afficherEntete(donnees);
        afficherAlertesGlobales(donnees);
        afficherMarqueurs(donnees);
        if (siteSelectionne) {
          // Si un site était ouvert, on rafraîchit son détail
          const site = donnees.sites.find(s => s.site_id === siteSelectionne);
          if (site) afficherDetailSite(site);
        }
      } catch (e) {
        console.error("Échec chargement date " + dateStr, e);
        document.getElementById("meta-maj").textContent = "Données indisponibles pour " + dateStr;
      }
    }

    function afficherEntete(d) {
      const el = document.getElementById("meta-maj");
      const horodatage = d.horodatage_generation_utc || "";
      let suffixe = "";
      if (horodatage) {
        const dt = new Date(horodatage);
        suffixe = ` (générée le ${dt.toLocaleDateString("fr-FR")} à ${dt.toLocaleTimeString("fr-FR", {hour: "2-digit", minute: "2-digit"})} UTC)`;
      }
      el.textContent = `Données du ${d.date}${suffixe}`;
    }

    function afficherAlertesGlobales(d) {
      const el = document.getElementById("alerts-globales");
      const av = d.avertissements_globaux || [];
      if (av.length === 0) {
        el.innerHTML = "";
        return;
      }
      el.innerHTML = av.map(escapeHtml).join(" · ");
    }

    function peuplerSelectDates(dates) {
      const select = document.getElementById("date-select");
      select.innerHTML = "";
      dates.forEach(d => {
        const o = document.createElement("option");
        o.value = d;
        o.textContent = d;
        select.appendChild(o);
      });
      select.addEventListener("change", e => chargerDate(e.target.value));
    }

    function escapeHtml(s) {
      if (s == null) return "";
      return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }

    async function init() {
      initCarte();
      try {
        const r = await fetch(`data/manifest.json?t=${Date.now()}`);
        manifest = await r.json();
        if (!manifest.dates || manifest.dates.length === 0) {
          document.getElementById("meta-maj").textContent = "Aucune donnée disponible pour le moment.";
          return;
        }
        peuplerSelectDates(manifest.dates);
        chargerDate(manifest.derniere_date || manifest.dates[0]);
      } catch (e) {
        console.error(e);
        document.getElementById("meta-maj").textContent = "Erreur de chargement du manifest.";
      }
    }
    init();
  })();
  </script>
</body>
</html>
"""


def generer_html() -> Path:
    """Écrit le fichier docs/index.html. Le HTML ne change pas (toutes
    les données sont chargées dynamiquement) — on l'écrit néanmoins à
    chaque exécution pour garantir qu'il est à jour."""
    chemin = DOSSIER_DOCS / "index.html"
    chemin.write_text(HTML_TEMPLATE, encoding="utf-8")
    logger.info("Tableau de bord généré : %s", chemin)
    return chemin


def _recalculer_scores_sentinel(site: dict, fai_stats: dict | None, ndvi_stats: dict | None, poids_base: dict) -> None:
    """Recalcule les valeurs FAI/NDVI dans previsions[] à partir des stats brutes.

    Reproduit la logique de compute_risk._score_fai / _score_ndvi pour les
    jours où les crédits CDSE étaient épuisés au moment de la collecte.
    La date des stats est antérieure au jour affiché : l'information est
    présentée avec est_fallback=True pour indiquer qu'il s'agit d'un proxy.
    """
    # Score FAI (0-100) : FAI p75 * 2000, saturé à 100
    score_fai = None
    if fai_stats:
        val = fai_stats.get("percentile_75") or fai_stats.get("percentile_50") or fai_stats.get("mean")
        sc = fai_stats.get("sampleCount") or 0
        if val is not None and sc >= 50:
            try:
                score_fai = round(max(0.0, min(100.0, float(val) * 2000)), 1)
            except (TypeError, ValueError):
                pass

    # Score NDVI (0-100) : NDVI mean * 250, saturé à 100
    score_ndvi = None
    if ndvi_stats and ndvi_stats.get("mean") is not None:
        try:
            score_ndvi = round(max(0.0, min(100.0, float(ndvi_stats["mean"]) * 250)), 1)
        except (TypeError, ValueError):
            pass

    if score_fai is None and score_ndvi is None:
        return  # rien à recalculer

    # Recalculer pour chaque horizon de prévision
    for prev in site.get("previsions", []):
        facteurs = prev.get("facteurs", {})
        # Déterminer quels facteurs sont disponibles après injection
        disponibles = {k for k, f in facteurs.items() if f.get("disponible")}
        if score_fai is not None:
            disponibles.add("fai_zone_2")
        if score_ndvi is not None:
            disponibles.add("ndvi_zone_1")

        # Re-normaliser les poids parmi les facteurs disponibles
        poids_actifs = {k: poids_base.get(k, 0) for k in disponibles}
        total_poids = sum(poids_actifs.values())
        if total_poids == 0:
            continue

        # Mettre à jour FAI
        if score_fai is not None and "fai_zone_2" in facteurs:
            facteurs["fai_zone_2"]["valeur"] = score_fai
            facteurs["fai_zone_2"]["disponible"] = True
            facteurs["fai_zone_2"]["poids_applique"] = round(poids_actifs["fai_zone_2"] / total_poids, 3)

        # Mettre à jour NDVI
        if score_ndvi is not None and "ndvi_zone_1" in facteurs:
            facteurs["ndvi_zone_1"]["valeur"] = score_ndvi
            facteurs["ndvi_zone_1"]["disponible"] = True
            facteurs["ndvi_zone_1"]["poids_applique"] = round(poids_actifs["ndvi_zone_1"] / total_poids, 3)

        # Recalculer les poids des autres facteurs avec la nouvelle normalisation
        for k, f in facteurs.items():
            if k in ("fai_zone_2", "ndvi_zone_1"):
                continue
            if f.get("disponible") and k in poids_actifs:
                facteurs[k]["poids_applique"] = round(poids_actifs[k] / total_poids, 3)

        # Recalculer le score global
        score_total = sum(
            (facteurs[k].get("valeur") or 0) * facteurs[k].get("poids_applique", 0)
            for k in facteurs if facteurs[k].get("disponible")
        )
        prev["score"] = round(score_total, 1)


def patcher_fallback_sentinel(dates_disponibles: list[str]) -> None:
    """Pour chaque JSON de docs/data/, si un site n'a pas d'images Sentinel
    (crédits CDSE épuisés ou pas de passage), injecte les dernières images
    disponibles depuis un JSON précédent, avec les stats FAI/NDVI et un drapeau
    'est_fallback' pour indiquer que les données sont antérieures au jour affiché.
    """
    # Deux caches indépendants par site_id :
    # - cache_img : dernières images connues dont les fichiers existent sur disque
    # - cache_stats : dernières valeurs FAI/NDVI connues (indépendant de l'existence des fichiers)
    cache: dict[str, dict] = {}        # images
    cache_stats: dict[str, dict] = {}  # stats FAI/NDVI

    # Parcourir du plus ancien au plus récent pour construire le cache
    for date_str in sorted(dates_disponibles):
        chemin = DOSSIER_DOCS_DATA / f"{date_str}.json"
        if not chemin.exists():
            continue
        donnees = charger_json(chemin)
        sites = donnees.get("sites", [])
        modifie = False

        for site in sites:
            site_id = site.get("site_id")
            if not site_id:
                continue
            sentinel = site.get("sentinel") or {}

            img_cot = sentinel.get("image_miniature")
            img_pel = sentinel.get("image_miniature_pelagique")
            date_img = sentinel.get("image_la_plus_recente")

            # Cache des stats FAI/NDVI (indépendant de l'existence des fichiers image)
            if sentinel.get("fai_zone_2") or sentinel.get("ndvi_zone_1"):
                cache_stats[site_id] = {
                    "fai_zone_2":  sentinel.get("fai_zone_2"),
                    "ndvi_zone_1": sentinel.get("ndvi_zone_1"),
                    "image_la_plus_recente": date_img,
                }

            # Vérifier que les fichiers image existent réellement sur disque
            # (le JSON peut référencer des chemins dont les fichiers ont été supprimés)
            if img_cot and not (DOSSIER_DOCS / img_cot).exists():
                img_cot = None
            if img_pel and not (DOSSIER_DOCS / img_pel).exists():
                img_pel = None

            # Si le JSON dit null mais que les fichiers existent sur disque pour
            # cette date (ex. : miniatures régénérées manuellement sans mise à jour
            # du JSON), on les récupère directement.
            if not img_cot:
                candidat = f"images/{date_str}/{site_id}.jpg"
                if (DOSSIER_DOCS / candidat).exists():
                    img_cot = candidat
            if not img_pel:
                candidat = f"images/{date_str}/{site_id}_pelagique.jpg"
                if (DOSSIER_DOCS / candidat).exists():
                    img_pel = candidat

            if img_cot or img_pel:
                # Images disponibles → mettre à jour le cache image
                # Si image_la_plus_recente est absent (stats nulles), récupérer depuis cache_stats
                if not date_img and cache_stats.get(site_id):
                    date_img = cache_stats[site_id].get("image_la_plus_recente")
                cache[site_id] = {
                    "image_miniature": img_cot,
                    "image_miniature_pelagique": img_pel,
                    "image_la_plus_recente": date_img or date_str,
                }
                # Mettre à jour le JSON si nécessaire
                maj = {}
                if img_cot != sentinel.get("image_miniature"):
                    maj["image_miniature"] = img_cot
                if img_pel != sentinel.get("image_miniature_pelagique"):
                    maj["image_miniature_pelagique"] = img_pel
                if date_img and not sentinel.get("image_la_plus_recente"):
                    maj["image_la_plus_recente"] = date_img
                # Propager stats FAI/NDVI manquantes depuis cache_stats + recalculer scores
                fai_injecte = cache_stats.get(site_id, {}).get("fai_zone_2") if not sentinel.get("fai_zone_2") else None
                ndvi_injecte = cache_stats.get(site_id, {}).get("ndvi_zone_1") if not sentinel.get("ndvi_zone_1") else None
                if fai_injecte:
                    maj["fai_zone_2"] = fai_injecte
                    maj["est_fallback"] = True
                if ndvi_injecte:
                    maj["ndvi_zone_1"] = ndvi_injecte
                    maj["est_fallback"] = True
                if maj:
                    sentinel.update(maj)
                    site["sentinel"] = sentinel
                    if fai_injecte or ndvi_injecte:
                        _recalculer_scores_sentinel(site, fai_injecte, ndvi_injecte, donnees.get("poids_appliques", {}))
                    modifie = True
            elif cache.get(site_id):
                # Pas d'images sur disque → injecter depuis cache image
                fb = cache[site_id]
                sentinel["image_miniature"] = fb["image_miniature"]
                sentinel["image_miniature_pelagique"] = fb["image_miniature_pelagique"]
                sentinel["image_la_plus_recente"] = fb["image_la_plus_recente"]
                # Propager stats FAI/NDVI manquantes depuis cache_stats + recalculer scores
                fai_injecte = cache_stats.get(site_id, {}).get("fai_zone_2") if not sentinel.get("fai_zone_2") else None
                ndvi_injecte = cache_stats.get(site_id, {}).get("ndvi_zone_1") if not sentinel.get("ndvi_zone_1") else None
                if fai_injecte:
                    sentinel["fai_zone_2"] = fai_injecte
                if ndvi_injecte:
                    sentinel["ndvi_zone_1"] = ndvi_injecte
                sentinel["est_fallback"] = True
                site["sentinel"] = sentinel
                if fai_injecte or ndvi_injecte:
                    _recalculer_scores_sentinel(site, fai_injecte, ndvi_injecte, donnees.get("poids_appliques", {}))
                modifie = True

        if modifie:
            enregistrer_json(chemin, donnees)

    logger.info("Fallback Sentinel appliqué (%d sites en cache)", len(cache))


def generer_dashboard_complet():
    """Pipeline : synchronise les données puis génère le HTML."""
    dates = synchroniser_donnees()
    patcher_fallback_sentinel(dates)
    chemin_html = generer_html()
    return {
        "html": str(chemin_html),
        "dates_disponibles": len(dates),
    }


if __name__ == "__main__":
    res = generer_dashboard_complet()
    logger.info("Dashboard prêt : %s (%d dates)", res["html"], res["dates_disponibles"])
