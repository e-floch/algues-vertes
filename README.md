# Surveillance algues vertes — Bretagne

Tableau de bord prédictif quotidien d'échouage d'algues vertes (*Ulva spp.*) sur les côtes bretonnes.

Le système collecte chaque soir à **18h heure française** des données satellites (Sentinel-2), météorologiques (vent) et de marée, calcule un score de risque pour chaque site et chaque horizon **J+1 à J+7**, puis publie automatiquement la mise à jour sur une page web publique hébergée par GitHub Pages.

---

## Sommaire

1. [Vue d'ensemble](#1-vue-densemble)
2. [Installation pas à pas (Mac)](#2-installation-pas-à-pas-mac)
3. [Création des comptes et obtention des clés API](#3-création-des-comptes-et-obtention-des-clés-api)
4. [Première exécution en local](#4-première-exécution-en-local)
5. [Mise en ligne avec GitHub et GitHub Pages](#5-mise-en-ligne-avec-github-et-github-pages)
6. [Activer l'automatisation quotidienne (GitHub Actions)](#6-activer-lautomatisation-quotidienne-github-actions)
7. [Utilisation au quotidien](#7-utilisation-au-quotidien)
8. [Calibrer le modèle avec des observations terrain](#8-calibrer-le-modèle-avec-des-observations-terrain)
9. [Ajouter ou modifier un site de surveillance](#9-ajouter-ou-modifier-un-site-de-surveillance)
10. [Dépannage](#10-dépannage)

---

## 1. Vue d'ensemble

| Élément | Choix technique |
|---|---|
| Langage | Python 3.11+ |
| Hébergement | GitHub Pages (statique, gratuit, dépôt public) |
| Automatisation | GitHub Actions (cron quotidien à 17h UTC) |
| Stockage historique | Fichiers JSON versionnés dans le dépôt GitHub (un par jour) |
| Frontend | HTML + CSS + JavaScript pur, carte Leaflet via CDN |

**Sites surveillés** : Baie de Guissény, Baie de Douarnenez (5 plages, nord et sud), Locquirec (toute l'année), Bassin de Horn-Guillec (3 plages), Baie de Carantec.

**Sources de données** :
- **Sentinel-2** via Copernicus Data Space Ecosystem — NDVI sur les estrans (zones 0 et 1) et Floating Algae Index (FAI) en zone pélagique (zone 2)
- **Vent** via Météo-France AROME (clé requise) — fallback automatique sur Open-Meteo si la clé n'est pas configurée
- **Marées** : calcul harmonique simplifié à partir des constantes SHOM des ports de Brest et Roscoff (aucune clé requise)

**Modèle de score (0 à 100)** :

| Facteur | Poids par défaut | Indicateur utilisé |
|---|---|---|
| FAI médian en zone 2 (pélagique) | 40 % | Médiane p50 sur pixels eau (SCL=6) — sature à FAI = 0,05 |
| Vent favorable à l'échouage | 30 % | Direction + force (optimal 10-25 km/h) |
| Coefficient de marée | 20 % | Linéaire coef 20→0, coef 120→100 |
| NDVI médian en zone 1 (côtier) | 10 % | Linéaire 0→0, 0,4→100 |

> **Note technique (FAI)** : le score FAI utilise la **médiane** (percentile 50) plutôt que la moyenne pour éviter qu'un petit nombre de pixels aberrants (eau turbide, reflets solaires, bords de nuages mal classifiés) ne gonfle artificiellement le score. Si la zone contient moins de 50 pixels eau valides, le FAI est considéré comme non représentatif et ignoré. L'evalscript Statistics ne retient que les pixels SCL=6 (eau confirmée).

**Cache Sentinel-2** : pour économiser les crédits CDSE (~100 PU/site/run), les statistiques NDVI/FAI sont réutilisées jusqu'à 14 jours si l'image la plus récente est encore valide. Les miniatures (images couleur) sont elles retéléchargées à chaque run (~2 PU/site).

**Niveaux d'alerte** : 1 Veille (0-25), 2 Vigilance (26-50), 3 Alerte (51-75), 4 Critique (76-100).

> **Important** : Le modèle n'est pas encore calibré sur des observations terrain. La fonction `calibrate()` permet d'ajuster les pondérations à partir d'observations saisies manuellement (voir [section 8](#8-calibrer-le-modèle-avec-des-observations-terrain)).

---

## 2. Installation pas à pas (Mac)

> Toutes les commandes sont à coller dans **Terminal** (application Spotlight → "Terminal").

### 2.1 Installer Homebrew (gestionnaire de paquets pour Mac)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Le script vous demandera votre mot de passe Mac. À la fin, il affiche **deux commandes à copier-coller** pour ajouter Homebrew au `PATH` (selon votre puce, Apple Silicon ou Intel). **Copiez-collez ces deux commandes**, puis vérifiez :

```bash
brew --version
```

> **Attendu** : `Homebrew 4.x.x` (peu importe la version mineure).

### 2.2 Installer Python 3.11+ et Git

```bash
brew install python@3.11 git
```

Puis vérifier les versions installées :

```bash
python3 --version
git --version
```

> **Attendu** : `Python 3.11.x` (ou supérieur) et `git version 2.x.x`.

### 2.3 Récupérer le code du projet

Pour la première mise en place, créez un dossier de travail et clonez le dépôt (à adapter une fois que vous l'avez créé sur GitHub — voir [section 5](#5-mise-en-ligne-avec-github-et-netlify)).

```bash
mkdir -p ~/Documents/algues-vertes-projet
cd ~/Documents/algues-vertes-projet
# Si le dépôt n'existe pas encore sur GitHub, copier ici les fichiers fournis
# (le dossier algues-vertes/ que vous avez reçu).
```

### 2.4 Créer un environnement virtuel Python et installer les dépendances

```bash
cd ~/Documents/algues-vertes-projet/algues-vertes
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> **Attendu** : `Successfully installed requests-...`.

> 💡 À chaque nouvelle session Terminal, il faut réactiver l'environnement avec `source .venv/bin/activate` avant de lancer le pipeline.

---

## 3. Création des comptes et obtention des clés API

### 3.1 Compte GitHub (gratuit)

1. Aller sur <https://github.com/signup> et créer un compte avec votre email professionnel.
2. Configurer Git en local (à n'effectuer qu'une fois) :

```bash
git config --global user.name  "Votre Nom"
git config --global user.email "votre.email@exemple.fr"
```

3. Générer une clé SSH (pour pousser le code sans mot de passe à chaque fois) :

```bash
ssh-keygen -t ed25519 -C "votre.email@exemple.fr"
# Appuyer sur "Entrée" 3 fois (chemin par défaut, pas de passphrase)
cat ~/.ssh/id_ed25519.pub | pbcopy
```

> **Attendu** : la clé publique est copiée dans le presse-papier.

4. Sur GitHub : aller dans **Settings → SSH and GPG keys → New SSH key**, coller la clé, lui donner un titre (ex. "Mac Emilie"), et valider.
5. Tester :

```bash
ssh -T git@github.com
```

> **Attendu** : `Hi <votre-pseudo>! You've successfully authenticated...`

### 3.2 Compte Copernicus Data Space (Sentinel-2, gratuit)

> **Compte actif** : le projet utilise le compte `emilie.floch@gmail.com`. Les clés OAuth correspondantes sont dans le `.env` local et dans les GitHub Secrets du dépôt.

Pour créer un nouveau compte ou renouveler les clés :

1. Aller sur <https://dataspace.copernicus.eu/> et cliquer **Register**.
2. Une fois connecté, aller sur <https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings>.
3. Dans **OAuth Clients**, cliquer **Create New** :
   - Nom : `algues-vertes`
   - Confidentialité : **Confidential**
4. Copier le **Client ID** et le **Client Secret** (le secret ne sera affiché qu'une fois).
5. Mettre à jour le `.env` local **et** les GitHub Secrets (`CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET`).

> **Quota** : chaque compte gratuit dispose de 30 000 Processing Units (PU) par mois. Grâce au cache 14 jours, la consommation est réduite à ~2 PU/site/jour (miniatures seules) contre ~100 PU/site sans cache.

### 3.3 Compte Météo-France API Publique (vent, gratuit, optionnel)

> **Optionnel** : si vous ne créez pas de clé, le système utilisera **Open-Meteo** comme source de secours (gratuit, sans inscription). C'est suffisant pour démarrer.

1. <https://portail-api.meteofrance.fr/web/fr/> → **Inscription**.
2. Souscrire à l'API "**Données AROME**".
3. Dans votre tableau de bord développeur, copier l'**applicationId** (clé API).

### 3.4 AirBreizh — mesures H2S (qualité de l'air, gratuit, optionnel)

> **Optionnel** : si rien n'est configuré, le pipeline tente l'URL par défaut documentée et continue sans planter en cas d'échec.

AirBreizh publie en open data les mesures horaires de **H2S** (hydrogène sulfuré, gaz toxique produit par la décomposition des algues vertes) issues de son **Réseau Algues Vertes** : 17 points de mesure dans les baies bretonnes les plus touchées, opérationnel **du 15 mai au 15 octobre**, mises à jour mensuellement.

1. Ouvrir la fiche de métadonnées du flux H2S : <https://opendata.airbreizh.asso.fr/geonetwork/srv/fre/catalog.search#/metadata/353f3c26-c35e-434f-afd3-f54e0ae5e0ef>
2. Récupérer l'**URL du service WFS** et le **nom de la couche** (typename) — ces informations apparaissent dans la section "Services" ou "Liens" de la fiche.
3. Renseigner dans le `.env` :
   ```
   AIRBREIZH_WFS_URL=<l'URL récupérée>
   AIRBREIZH_LAYER=<le nom de la couche>
   ```

Le panneau de détail de chaque site affichera alors la dernière concentration H2S mesurée, la moyenne 24h, le maximum 7 jours et le seuil sanitaire associé (référence OMS). Le H2S **n'entre pas dans le calcul du score prédictif** : c'est une mesure observée (constat), pas une prévision.

**Sites couverts** (mapping fait dans `src/sites_config.py`) :
- Baie de Douarnenez Nord/Sud → stations Kerléven / Plage du Ris
- Locquirec → station Saint-Michel-en-Grève
- Baie de Guissény, Bassin de Horn-Guillec, Carantec → pas de station AirBreizh proche → "Pas de mesure disponible" affiché honnêtement.

Si AirBreizh ajoute une nouvelle station qui couvre l'un de vos sites actuellement non couverts, éditer `STATIONS_AIRBREIZH` puis le champ `station_airbreizh` du site concerné dans `src/sites_config.py`.

### 3.5 Hébergement GitHub Pages (gratuit, intégré à GitHub)

GitHub Pages est activé directement depuis le dépôt GitHub — aucun compte tiers nécessaire. Voir [section 5](#5-mise-en-ligne-avec-github-et-github-pages) pour l'activation.

### 3.6 Configurer le fichier .env en local

```bash
cd ~/Documents/algues-vertes-projet/algues-vertes
cp .env.example .env
open -a TextEdit .env
```

Remplir les clés obtenues ci-dessus. Le fichier `.env` est ignoré par `.gitignore` — il ne sera **jamais** poussé sur GitHub.

---

## 4. Première exécution en local

Avec l'environnement virtuel activé et le `.env` rempli :

```bash
cd ~/Documents/algues-vertes-projet/algues-vertes
source .venv/bin/activate
python src/run_pipeline.py
```

> **Attendu** :
> - Une série de logs `[INFO] collect_sentinel: Collecte Sentinel-2 pour ...`
> - Création d'un fichier `data/YYYY-MM-DD.json`
> - Création/mise à jour de `docs/index.html` et de `docs/data/`
> - Message final : `Tableau de bord prêt : .../docs/index.html (1 dates)`

Pour visualiser le tableau de bord en local :

```bash
cd docs
python3 -m http.server 8000
```

Puis ouvrir <http://localhost:8000> dans Safari ou Chrome. Pour arrêter le serveur, `Ctrl+C` dans le Terminal.

---

## 5. Mise en ligne avec GitHub et GitHub Pages

### 5.1 Créer le dépôt GitHub

1. <https://github.com/new> :
   - Nom : `algues-vertes`
   - Visibilité : **Public** (obligatoire pour GitHub Pages gratuit)
   - **Ne pas** initialiser avec un README (le fichier existe déjà)
2. Récupérer l'URL SSH affichée, par exemple `git@github.com:votre-pseudo/algues-vertes.git`.

> **Sécurité** : le dépôt est public mais aucune clé API n'est dans le code. Les clés sont dans le fichier `.env` local (ignoré par `.gitignore`) et dans les GitHub Secrets (chiffrés).

### 5.2 Pousser le code

Dans le Terminal, depuis le dossier `algues-vertes/` :

```bash
git init
git add .
git commit -m "Initialisation du projet"
git branch -M main
git remote add origin git@github.com:votre-pseudo/algues-vertes.git
git push -u origin main
```

> **Attendu** : `Branch 'main' set up to track 'origin/main'.`

### 5.3 Activer GitHub Pages

1. Sur GitHub, aller dans **Settings** de votre dépôt (onglet du haut).
2. Dans le menu gauche, cliquer **Pages**.
3. Sous **Source**, choisir **Deploy from a branch**.
4. Branch : **main** / Folder : **/docs** → cliquer **Save**.

Au bout de 1 à 2 minutes, GitHub affiche l'URL publique :
`https://votre-pseudo.github.io/algues-vertes/`

> **Attendu** : en ouvrant cette URL, le tableau de bord s'affiche.

> 💡 GitHub Pages ne propose pas de protection par mot de passe nativement. Le tableau de bord est public. Pour restreindre l'accès, une alternative est de passer à **GitHub Pro** (~4$/mois) qui permet les dépôts privés avec Pages, ou d'ajouter une authentification côté client dans le HTML.

### 5.4 Déploiement automatique

À chaque fois que GitHub Actions pousse un commit sur `main` (mise à jour quotidienne ou manuelle), GitHub Pages redéploie automatiquement le tableau de bord en quelques secondes — aucune action supplémentaire nécessaire.

---

## 6. Activer l'automatisation quotidienne (GitHub Actions)

### 6.1 Renseigner les secrets dans GitHub

Sur GitHub, dans votre dépôt → **Settings → Secrets and variables → Actions → New repository secret** :

| Nom du secret | Valeur |
|---|---|
| `CDSE_CLIENT_ID` | Client ID Copernicus (étape 3.2) |
| `CDSE_CLIENT_SECRET` | Client Secret Copernicus (étape 3.2) |
| `METEOFRANCE_API_KEY` | (optionnel) applicationId Météo-France |
| `SHOM_API_KEY` | (optionnel) clé SHOM |
| `AIRBREIZH_WFS_URL` | (optionnel) URL du service WFS AirBreizh H2S |
| `AIRBREIZH_LAYER` | (optionnel) nom de la couche WFS H2S |

> Les secrets ne sont jamais visibles dans les logs des workflows.

### 6.2 Vérifier que le workflow est actif

Sur GitHub → onglet **Actions**. Vous devez voir le workflow **« Mise à jour quotidienne du tableau de bord »**. Cliquer dessus, puis **Run workflow → Run** pour le tester immédiatement.

> **Attendu** : au bout de 2 à 3 minutes, le workflow se termine en vert. Un nouveau commit "Mise à jour automatique du …" apparaît sur la branche `main`.

GitHub Pages détecte automatiquement le push et redéploie le site (≈ 30 s).

### 6.3 Heure d'exécution

Le cron est paramétré sur `0 17 * * *` (17h UTC) :
- En **hiver** (UTC+1) → mise à jour à **18h heure française** ✅
- En **été** (UTC+2) → mise à jour à **19h heure française**

Pour avoir 18h toute l'année, il faudrait deux crons saisonniers ; la solution actuelle privilégie la simplicité.

---

## 7. Utilisation au quotidien

### 7.1 Consulter le tableau de bord

Aller sur `https://e-floch.github.io/algues-vertes/` — le tableau de bord s'affiche directement :
- **Carte** : un marqueur par site, coloré selon le niveau d'alerte J+1
- **Cliquer un marqueur** : ouvre le panneau latéral avec :
  - Niveaux d'alerte J+1 à J+7
  - Détail des facteurs (vent, marée, FAI, NDVI)
  - Date de la dernière image Sentinel-2
  - Graphique d'évolution du score sur 14 jours
- **Menu déroulant "Consulter une date"** : permet de voir le tableau de bord tel qu'il était à n'importe quelle date passée

### 7.2 Avertissements

Un bandeau jaune apparaît en haut si certaines données sont indisponibles ou dégradées (ex. couverture nuageuse trop forte → "Données Sentinel-2 du JJ/MM/AAAA").

---

## 8. Calibrer le modèle avec des observations terrain

Quand un échouage est observé sur le terrain, on peut comparer le niveau réel au niveau prédit et ajuster les pondérations :

```bash
cd ~/Documents/algues-vertes-projet/algues-vertes
source .venv/bin/activate

# Syntaxe : python src/compute_risk.py calibrate <site_id> <YYYY-MM-DD> <niveau_observe>
# niveau_observe : 1 = Veille, 2 = Vigilance, 3 = Alerte, 4 = Critique
python src/compute_risk.py calibrate guisseny_curnic 2026-05-04 3
```

> **Attendu** : `Nouveaux poids : {'fai_zone_2': 0.42, 'vent': 0.29, 'coef_maree': 0.19, 'ndvi_zone_1': 0.10}`

Le fichier `calibration.json` est mis à jour. Au prochain run du pipeline, les nouvelles pondérations seront utilisées automatiquement.

> Les identifiants de site sont listés dans `src/sites_config.py` (champ `id`).

---

## 9. Ajouter ou modifier un site de surveillance

1. Ouvrir `src/sites_config.py`.
2. Repérer la plage sur Google Maps, faire un **clic droit sur le point central de la plage** → copier les coordonnées GPS.
3. Dupliquer une entrée existante du tableau `SITES` et renseigner :

```python
{
    "id": "nom_court_unique",                     # identifiant interne (sans accent ni espace)
    "nom": "Commune — Plage de XYZ",              # nom lisible affiché sur la carte
    "baie": "Baie de XXX",                        # baie de rattachement (utilisée pour le vent favorable)
    "lat": 48.1234,                               # latitude en degrés décimaux
    "lon": -4.5678,                               # longitude en degrés décimaux
    "port_maree": "Brest",                        # "Brest" ou "Roscoff" (port de référence)
    "year_round": False,                          # True si surveillance toute l'année
},
```

4. Pousser le commit :

```bash
git add src/sites_config.py
git commit -m "Ajout du site XYZ"
git push
```

5. Lancer manuellement le workflow GitHub Actions (onglet Actions → Run workflow) **ou** attendre la mise à jour automatique du soir.

> Pour ajouter une nouvelle baie avec une direction de vent favorable spécifique, ajouter aussi une entrée dans `VENT_FAVORABLE_PAR_BAIE` (fichier `src/compute_risk.py`).

---

## 10. Dépannage

### "Sentinel-2 indisponible"

- Vérifier que `CDSE_CLIENT_ID` et `CDSE_CLIENT_SECRET` sont corrects dans les GitHub Secrets (Settings → Secrets and variables → Actions).
- Si le log indique **"Crédits CDSE épuisés"** : le quota de 30 000 PU du mois est atteint. Créer un nouveau compte sur <https://dataspace.copernicus.eu/> avec une autre adresse email, générer de nouveaux OAuth Clients, et mettre à jour les GitHub Secrets.
- Le service CDSE peut être en maintenance : réessayer le lendemain. Grâce au cache 14 jours, le tableau de bord continuera à afficher les données Sentinel existantes.

### "Score FAI = 100 sans algues visibles sur l'image"

Le FAI utilise la **médiane** (p50) des pixels eau (SCL=6). Si ce score reste anormalement élevé :
- Vérifier la valeur `percentile_50` dans le JSON du jour (`data/YYYY-MM-DD.json` → `sentinel.fai_zone_2`) — si elle est > 0,05, une anomalie persiste dans la zone pélagique (bloom réel ou turbidité).
- Si `sampleCount` < 50, le FAI est ignoré (trop peu de pixels eau valides).

### Le workflow GitHub Actions échoue

- Onglet **Actions → Workflow → run en échec** : lire les logs pour identifier l'étape qui plante.
- Cause fréquente : un secret a été modifié ou supprimé. Aller dans **Settings → Secrets and variables → Actions** et vérifier qu'ils existent.

### Le site GitHub Pages ne se met pas à jour

- Vérifier que le dernier commit a bien été poussé sur `main` (onglet **Code** du dépôt).
- Sur GitHub → onglet **Actions** : vérifier que le workflow s'est terminé en vert.
- Sur GitHub → **Settings → Pages** : vérifier que la source est bien `main / docs`. Si une erreur de déploiement apparaît, cliquer **Visit site** pour voir si c'est un problème de cache navigateur.

### "ModuleNotFoundError: requests" en local

- L'environnement virtuel n'est pas activé : relancer `source .venv/bin/activate` puis `pip install -r requirements.txt`.

### Réinitialiser la calibration

```bash
rm calibration.json
git add calibration.json
git commit -m "Réinitialisation de la calibration"
git push
```

---

## Licence et crédits

Code original sous licence MIT. Données : © Copernicus / ESA (Sentinel-2), © Météo-France / Open-Meteo, © SHOM (constantes harmoniques), © OpenStreetMap (fond cartographique).
