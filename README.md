# Dataviz-_theme_DPE-vs-Enedis-   
groupe:
Victor Eloy
Ala eddine Yakoubi
# Dashboard DPE vs Enedis

## Présentation du projet

Ce projet de **Data Visualisation** a pour objectif de comparer la **consommation électrique estimée par le DPE** avec la **consommation réelle mesurée par Enedis**.

L'objectif principal est de répondre à la question suivante :

> **La consommation électrique réelle des logements est-elle inférieure, proche ou supérieure à l'estimation fournie par le DPE ?**

Le dashboard permet également d'étudier les écarts selon plusieurs caractéristiques du logement : classe DPE, type de logement, surface, nombre d'occupants, usages électriques et localisation géographique.

---

## Objectifs

Le projet permet de :

- comparer la consommation **DPE estimée** et la consommation **Enedis mesurée** ;
- visualiser les écarts de consommation ;
- analyser les résultats par **classe DPE de A à G** ;
- comparer plusieurs départements ;
- analyser la variabilité des écarts entre les logements ;
- étudier l'influence de la surface, du type de logement et du nombre d'occupants ;
- visualiser les résultats sur une carte de France ;
- afficher des KPI synthétiques ;
- filtrer et explorer les données de manière interactive.

---

## Technologies utilisées

- **Python**
- **Dash**
- **Plotly**
- **Pandas**
- **NumPy**

---

## Données utilisées

### DPE

Le DPE fournit une estimation conventionnelle de la consommation énergétique d'un logement.

Les informations utilisées peuvent notamment contenir :

- classe DPE ;
- consommation estimée ;
- surface habitable ;
- type de logement ;
- adresse ;
- département ;
- équipements et usages énergétiques.

### Enedis

Les données Enedis représentent la consommation électrique réellement observée.

Le projet cherche ensuite à rapprocher les données DPE et Enedis afin de mesurer les différences entre :

```text
Consommation réelle Enedis
            VS
Consommation estimée DPE
```

---

## Indicateurs principaux

Le dashboard peut notamment afficher :

- écart entre Enedis et DPE ;
- ratio consommation mesurée / consommation estimée ;
- part des logements où Enedis dépasse le DPE ;
- consommation par m² ;
- variabilité des écarts ;
- comparaison entre les classes DPE ;
- comparaison entre plusieurs départements ;
- distribution des profils : inférieur, proche ou supérieur au DPE.

---

## Structure du projet

Exemple de structure :

```text
Enedis VS DPE/
│
├── app.py
├── analyse.py
├── cartographie.py
├── requirements.txt
├── README.md
│
├── dataset_electrique_enrichi_2023_2024.csv
│
├── assets/
│   ├── style.css
│   └── images/
│
└── autres fichiers Python du projet
```

La structure exacte peut varier selon la version du projet.

---

# Installation et exécution

## 1. Cloner le projet

```bash
git clone https://github.com/lolo150/Dataviz-_theme_DPE-vs-Enedis-.git
```

Puis :

```bash
cd Dataviz-_theme_DPE-vs-Enedis-
```

---

## 2. Vérifier Python

```bash
python --version
```

ou :

```bash
py --version
```

---

## 3. Installer les dépendances

Si le projet contient `requirements.txt` :

```bash
pip install -r requirements.txt
```

ou :

```bash
python -m pip install -r requirements.txt
```

---

## 4. Lancer le dashboard

Si le fichier principal est `app.py` :

```bash
python app.py
```

ou :

```bash
py app.py
```

Après le lancement, ouvrir dans le navigateur :

```text
http://127.0.0.1:8050/
```

---

## Exécution directe sous Windows PowerShell

```powershell
cd "C:\Users\DELL\Desktop\Masteroffic\Mastere Data engenner\M2\Cours M2\Data viz\codecloud3\codev\Enedis VS DPE"

python -m pip install -r requirements.txt

python app.py
```

---

## Si le fichier principal porte un autre nom

Par exemple, si l'application principale s'appelle `dashboard.py` :

```bash
python dashboard.py
```

Il faut exécuter le fichier contenant l'application Dash et le lancement du serveur.

---

# Environnement virtuel — optionnel

Création :

```bash
python -m venv venv
```

Activation sous Windows :

```powershell
venv\Scripts\activate
```

Installation :

```bash
pip install -r requirements.txt
```

Lancement :

```bash
python app.py
```

Pour quitter l'environnement :

```bash
deactivate
```

---

# Exécution avec Docker

Cette partie s'applique si le projet contient un `Dockerfile`.

Construire l'image :

```bash
docker build -t dpe-enedis-dashboard .
```

Lancer le conteneur :

```bash
docker run -p 8050:8050 dpe-enedis-dashboard
```

Puis ouvrir :

```text
http://localhost:8050
```

Pour Docker, l'application Dash doit écouter sur toutes les interfaces, par exemple :

```python
app.run(host="0.0.0.0", port=8050, debug=False)
```

---

# Dataset volumineux

Le projet utilise notamment :

```text
dataset_electrique_enrichi_2023_2024.csv
```

Lors de l'exécution, vérifier que ce fichier se trouve bien dans le chemin attendu par le code.

Exemple :

```python
pd.read_csv("dataset_electrique_enrichi_2023_2024.csv")
```

GitHub impose une limite de taille par fichier. Le dataset peut donc être réduit ou découpé avant d'être ajouté au dépôt.

---

# Fonctionnement du dashboard

## Vue générale

La vue générale présente les principaux KPI ainsi qu'une carte permettant d'identifier rapidement les différences entre les territoires.

## Carte interactive

La carte permet de sélectionner un ou plusieurs départements.

La sélection peut être répercutée sur les KPI et les autres graphiques grâce au principe de **Linking entre les vues**.

## Comparaison DPE / Enedis

Les graphiques permettent de déterminer si la consommation Enedis est :

- inférieure à l'estimation DPE ;
- proche de l'estimation DPE ;
- supérieure à l'estimation DPE.

## Variabilité

Le dashboard permet aussi d'observer la dispersion et de répondre à la question :

> **L'écart moyen cache-t-il de grandes différences entre les adresses ?**

## Comparaison de plusieurs départements

Le projet peut utiliser le principe des **Small Multiples** afin de comparer plusieurs départements avec des graphiques utilisant la même échelle.

---

# Interactions

Le dashboard utilise notamment :

- filtres ;
- sélection de départements ;
- boutons interactifs ;
- survol ;
- tooltips ;
- vues liées ;
- comparaison entre plusieurs catégories ;
- drill-down partiel entre la France et les départements.

---

# Problématique

Une étiquette énergétique donne une estimation standardisée de la performance d'un logement.

Cependant, la consommation réelle dépend aussi de nombreux facteurs :

- comportement des occupants ;
- nombre d'occupants ;
- surface ;
- température de chauffage ;
- équipements électriques ;
- qualité de l'isolation ;
- habitudes de consommation.

Le projet cherche donc à déterminer dans quelle mesure la consommation réellement observée correspond aux estimations du DPE.

---

# Limites

Les résultats doivent être interprétés avec prudence.

Le DPE correspond à une consommation conventionnelle calculée dans des conditions standardisées, tandis que la consommation Enedis représente une consommation réellement observée.

Une différence entre les deux ne signifie donc pas automatiquement que le DPE est incorrect.

---

# Auteur

Projet réalisé dans le cadre du module **Data Visualisation — YNOV Campus**.

Année universitaire : **2026–2027**.
