"""Dashboard DPE vs Enedis 2023-2024 · Dash + Plotly.
Lancer : python app.py  →  http://127.0.0.1:8050

Fichier de données attendu dans le même dossier :
    dataset_electrique_enrichi_2023_2024.csv
(CSV d'origine + colonnes unifiées Enedis / DPE, écarts, gains, flags de population).
"""
from functools import lru_cache
from pathlib import Path
import json
import textwrap
import urllib.request
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, dash_table, ctx, no_update
from dash.exceptions import PreventUpdate
from plotly.subplots import make_subplots
from usages_electriques import figures_usages, COLONNES_DETAIL
from calculs import differences, profils, panel, resume_facteur, eligibles_dispersion
from cartographie import fig_carte as carte_complete

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
DOSSIER = Path(__file__).resolve().parent
FICHIER = DOSSIER / "dataset_electrique_enrichi_2023_2024.csv"
CLASSES = list("ABCDEFG")
TARIF = 0.25                      # €/kWh (hypothèse du dataset)
MIN_STRATE = 10                   # effectif minimal par classe et par strate (KPI 2)

# Palette sûre pour le daltonisme (bleu / orange) + redondance par motif et position
COULEUR_DPE = "#246BB0"
COULEUR_ENEDIS = "#E59842"
COULEUR_NEUTRE = "#205F79"
COULEUR_TEXTE = "#273A50"
COULEUR_FOND = "#F6F8FB"
COULEUR_ALERTE = "#D62828"
COULEUR_GRILLE = "#E8EDF2"

GEOJSON_URL = ("https://raw.githubusercontent.com/gregoiredavid/france-geojson/"
               "master/departements-version-simplifiee.geojson")
GEOJSON_LOCAL = DOSSIER / "departements.geojson"

COLONNES = ["id_adresse_panel", "annee", "adresse", "commune", "code_departement",
            "nom_departement", "classe_dpe", "type_logement", "energie_chauffage",
            "tranche_surface", "surface_m2", "nb_logements",
            "conso_enedis_unifiee_kwh", "conso_dpe_unifiee_kwh",
            "ecart_kwh", "ecart_pct", "gain_kwh", "gain_eur",
            "donnee_simulee", "population_kpi_1_4", "population_kpi_5_6",
            "conso_appareils_scenario_kwh", "conso_usages_dpe_scenario_kwh",
            "economie_equipements_kwh", "economie_equipements_eur",
            "retenu_kpi7", "variation_enedis_pct", "variation_dpe_pct",
            "conso_dpe_chauffage_kwh", "conso_dpe_ecs_kwh", "conso_dpe_refroidissement_kwh",
            "conso_dpe_eclairage_kwh", "conso_dpe_auxiliaires_kwh"]


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------
def charger_geojson():
    if not GEOJSON_LOCAL.exists():
        raise FileNotFoundError("Conserver departements.geojson dans le dossier de l'application.")
    return json.loads(GEOJSON_LOCAL.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------
def charger_donnees():
    if not FICHIER.exists():
        raise FileNotFoundError(f"{FICHIER.name} introuvable dans {DOSSIER}.")
    d = pd.read_csv(FICHIER, encoding="utf-8-sig", low_memory=False,
                    dtype={"code_departement": str, "code_commune": str, "code_postal": str})
    d = d.loc[d.annee.isin([2023, 2024])].copy()
    required = ["calcul_ecart_possible", "comparaison_reelle_validee", "statut_comparabilite",
                "statut_surface_analyse", "energie_chauffage", "source_enedis", "source_dpe"]
    missing = [c for c in required if c not in d]
    if missing:
        raise ValueError("Utilisez le CSV électrique audité ; colonnes manquantes : " + ", ".join(missing))
    for c in ["donnee_simulee", "calcul_ecart_possible", "comparaison_reelle_validee"]:
        d[c] = d[c].astype(str).str.lower().isin(["true", "1", "oui"])
    d = d.loc[d.energie_chauffage.str.strip().eq("Électricité")].copy()
    part_simulee = d.donnee_simulee.mean() * 100
    numeric = np.isfinite(d.conso_enedis_unifiee_kwh) & np.isfinite(d.conso_dpe_unifiee_kwh)
    numeric &= d.conso_enedis_unifiee_kwh.ge(0) & d.conso_dpe_unifiee_kwh.gt(0)
    d = d.loc[d.calcul_ecart_possible & numeric].copy()
    missing_detail = [c for c in COLONNES_DETAIL if c not in d]
    if missing_detail:
        raise ValueError("Le CSV enrichi est requis : détails appareils manquants.")
    d["equipements_groupe"] = d.nb_equipements_electromenagers_scenario.map(
        lambda x: "Non mesuré" if pd.isna(x) else f"{int(x)} équipements recensés")
    d["nature_donnees"] = np.where(d.donnee_simulee, "Donnée simulée", "Sources originales · à vérifier")
    if d.duplicated(["id_adresse_panel", "annee"]).any():
        raise ValueError("Doublons adresse × année : vérifier le fichier de données.")
    d["ecart_kwh"] = d.conso_enedis_unifiee_kwh - d.conso_dpe_unifiee_kwh
    d["ecart_pct"] = d.ecart_kwh / d.conso_dpe_unifiee_kwh * 100
    d["ecart_absolu_kwh"] = d.ecart_kwh.abs()
    d["gain_kwh"] = -d.ecart_kwh
    d["gain_eur"] = d.gain_kwh * TARIF
    d["dept_code"] = d.code_departement.astype(str).str.zfill(2)
    d["classe_dpe"] = pd.Categorical(d.classe_dpe, CLASSES + ["Mixte"], ordered=True)
    d["annee"] = d.annee.astype(int)
    # Catégories descriptives calculées en mémoire ; aucune modification du CSV.
    d["occupation_groupe"] = d.nb_occupants_scenario.map(
        lambda x: "Non mesurée" if pd.isna(x) else ("5 personnes et +" if x >= 5 else f"{int(x)} personne(s)"))
    appareils = pd.to_numeric(d.conso_appareils_scenario_kwh, errors="coerce")
    d["appareils_groupe"] = pd.cut(appareils, [-np.inf,1000,2000,np.inf],
        labels=["≤ 1 000 kWh/an", "1 000–2 000 kWh/an", "> 2 000 kWh/an"]).astype(object).fillna("Non mesurée")
    for col in ["occupation_groupe", "appareils_groupe"]:
        d.loc[~d.donnee_simulee, col] = "Non mesurée"
    return d, part_simulee


D, PART_SIMULEE = charger_donnees()
GEOJSON = charger_geojson()
if GEOJSON is None:
    raise SystemExit("Impossible de charger le GeoJSON des départements.")

NOMS_DEPT = {str(f["properties"]["code"]).zfill(2): f["properties"].get("nom", "")
             for f in GEOJSON["features"]}
NOMS_DEPT.update(D.drop_duplicates("dept_code").set_index("dept_code").nom_departement.to_dict())
TOUS_DEPT = sorted(str(f["properties"]["code"]).zfill(2) for f in GEOJSON["features"])
DEPTS_DONNEES = sorted(D.dept_code.unique())
TRANCHES = [t for t in ["0-30", "30-50", "50-70", "70-90", "90-120", ">120"]
            if t in set(D.tranche_surface)]


# ---------------------------------------------------------------------------
# Traitement
# ---------------------------------------------------------------------------
@lru_cache(maxsize=256)
def _filtrer(annee, source, depts, communes, dpes, tranches):
    source = "all"  # Périmètre complet du CSV ; origine conservée dans les colonnes.
    q = D
    if annee != "all":
        q = q.loc[q.annee == int(annee)]
    if source == "reel":
        q = q.loc[~q.donnee_simulee]
    elif source == "simule":
        q = q.loc[q.donnee_simulee]
    elif source == "valide":
        q = q.loc[~q.donnee_simulee & q.comparaison_reelle_validee]
    if depts:
        q = q.loc[q.dept_code.isin(depts)]
    if communes:
        q = q.loc[q.commune.isin(communes)]
    if dpes:
        q = q.loc[q.classe_dpe.isin(dpes)]
    if tranches:
        q = q.loc[q.tranche_surface.isin(tranches)]
    return q


def lire(annee, source, depts, communes, dpes, tranches, selection=None, unite="kwh", profils_sel=None):
    eff = tuple(selection) if selection else tuple(depts or [])
    q = _filtrer(annee or "all", source or "all", eff, tuple(communes or []),
                 tuple(dpes or []), tuple(tranches or []))
    for col, valeurs in (profils_sel or {}).items():
        if valeurs:
            q = q.loc[q[col].isin(valeurs)]
    return convertir(q, unite or "kwh")


STRATES = ["annee", "tranche_surface", "energie_chauffage", "type_logement"]


def gains_classes(q):
    return differences(q, minimum=MIN_STRATE).rename(columns={
        "conso_enedis_unifiee_kwh": "enedis_kwh", "conso_dpe_unifiee_kwh": "dpe_kwh",
        "conso_enedis_unifiee_kwh_pct": "enedis_pct", "conso_dpe_unifiee_kwh_pct": "dpe_pct"})


def compute_kpis(q, transition="F→E"):
    """Deux KPI : biais et dispersion des écarts."""
    if q.empty:
        return None
    eligible = eligibles_dispersion(q)
    k = {"lignes": len(q), "adresses": q.id_adresse_panel.nunique(),
         "ecart": q.ecart_kwh.mean(),
         "ecart_pct": q.ecart_kwh.sum() / q.conso_dpe_unifiee_kwh.sum() * 100,
         "ecart_type": eligible.ecart_kwh.std(),
         "adresses_dispersion": eligible.id_adresse_panel.nunique()}
    return k


def fmt(x, dec=0):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def fs(x, dec=0):
    """Nombre avec signe explicite (+ / −) : le signe double l'information portée par la position."""
    if x is None or pd.isna(x):
        return "—"
    return ("+" if x > 0 else "−" if x < 0 else "") + fmt(abs(x), dec)


# Unités : (libellé kWh, décimales, libellé axe, libellé €, décimales €)
UNITES = {"kwh": ("kWh/an", 0, "kWh / logement / an", "€/an", 0),
          "m2": ("kWh/m²/an", 1, "kWh / m² / an", "€/m²/an", 2)}
USAGES = [("conso_dpe_chauffage_kwh", "Chauffage", "#D55E00", "/"),
          ("conso_dpe_ecs_kwh", "Eau chaude sanitaire", "#0072B2", ""),
          ("conso_dpe_refroidissement_kwh", "Refroidissement", "#56B4E9", "."),
          ("conso_dpe_eclairage_kwh", "Éclairage", "#F0E442", "x"),
          ("conso_dpe_auxiliaires_kwh", "Auxiliaires", "#009E73", "+")]
COLS_ECHELLE = ["conso_enedis_unifiee_kwh", "conso_dpe_unifiee_kwh", "ecart_kwh", "gain_kwh", "gain_eur",
                "conso_appareils_scenario_kwh", "conso_usages_dpe_scenario_kwh",
                "economie_equipements_kwh", "economie_equipements_eur"] + [u[0] for u in USAGES] + ["ecart_absolu_kwh", "ecart_usages_scenario_kwh",
    "ecart_appareils_scenario_kwh", "conso_apres_remplacement_scenario_kwh",
    "economie_remplacement_scenario_eur", "ecart_apres_remplacement_scenario_kwh"]


def convertir(q, unite):
    """kWh/m²/an : chaque consommation est ramenée à la surface du logement."""
    if unite != "m2" or q.empty:
        return q
    # Le CSV audité laisse les intensités originales vides : surface proxy.
    q = q.loc[q.conso_enedis_unifiee_kwh_m2.notna()
              & q.conso_dpe_unifiee_kwh_m2.notna() & q.surface_m2.gt(0)].copy()
    cols = list(dict.fromkeys(c for c in COLS_ECHELLE + COLONNES_DETAIL if c in q.columns))
    q[cols] = q[cols].div(q.surface_m2, axis=0)
    return q


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def habiller(fig, titre, hauteur=330):
    lignes = textwrap.wrap(titre, width=48, break_long_words=False)
    titre = "<br>".join(lignes)
    fig.update_layout(
        height=hauteur, template="plotly_white",
        font=dict(family="Arial", size=12, color=COULEUR_TEXTE),
        title=dict(text=titre, font=dict(size=14), x=0, xanchor="left"),
        margin=dict(l=10, r=10, t=75 + 17 * len(lignes), b=50),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, title="", font=dict(size=16)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(showgrid=False, linecolor="#B5C0CC", tickfont=dict(size=14), title_font=dict(size=14), automargin=True)
    fig.update_yaxes(gridcolor=COULEUR_GRILLE, zerolinecolor="#8795A6", tickfont=dict(size=14), title_font=dict(size=14), automargin=True)
    fig.update_traces(textfont_size=14, selector=dict(type="bar"))
    return fig


def fig_vide(titre="Aucune donnée pour ces filtres", hauteur=330):
    f = go.Figure()
    f.add_annotation(text="Aucune donnée admissible ou effectif insuffisant. Vérifiez les filtres, l’origine et l’unité.",
                     showarrow=False, font=dict(size=12, color="#66758A"))
    f.update_xaxes(visible=False)
    f.update_yaxes(visible=False)
    return habiller(f, titre, hauteur)






def fig_ecart(q, unite="kwh"):
    """Moyennes des deux sources sur les mêmes observations, par classe."""
    e, d = "conso_enedis_unifiee_kwh", "conso_dpe_unifiee_kwh"
    base = q.loc[np.isfinite(q[e]) & np.isfinite(q[d])].copy()
    if base.empty:
        return fig_vide("Consommations par classe · aucune donnée")
    g = base.groupby("classe_dpe", observed=True).agg(
        enedis=(e, "mean"), dpe=(d, "mean"), n=("id_adresse_panel", "nunique")
    ).reindex(CLASSES).dropna(subset=["enedis", "dpe"])
    g["ecart"] = g.enedis - g.dpe
    fig = go.Figure()
    for col, nom, couleur, motif in [("dpe", "DPE estimé", COULEUR_DPE, "/"),
                                    ("enedis", "Enedis", COULEUR_ENEDIS, "")]:
        fig.add_trace(go.Bar(x=g.index, y=g[col], name=nom,
            marker_color=couleur, marker_pattern_shape=motif,
            customdata=np.c_[g.dpe, g.enedis, g.ecart, g.n],
            hovertemplate=("Classe %{x}<br>DPE moyen : %{customdata[0]:,.1f}"
                "<br>Enedis moyen : %{customdata[1]:,.1f}"
                "<br>Écart Enedis − DPE : %{customdata[2]:+,.1f}"
                "<br>%{customdata[3]:.0f} adresses<extra>%{fullData.name}</extra>")))
    fig = habiller(fig, "DPE et Enedis : consommations moyennes par classe")
    fig.update_layout(barmode="group", margin=dict(l=65, r=15, t=110, b=55),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(size=16)))
    fig.update_xaxes(title="Classe DPE", categoryorder="array", categoryarray=CLASSES, automargin=True)
    fig.update_yaxes(title=UNITES[unite][2], rangemode="tozero", automargin=True)
    return fig












FACTEURS = {"qualite_isolation": "Qualité de l’isolation", "periode_construction": "Période de construction",
            "energie_chauffage": "Énergie de chauffage", "chauffage_installation": "Installation de chauffage",
            "type_logement": "Type de logement"}







def fig_histogramme(q, unite="kwh"):
    if q.empty:
        return fig_vide("Distribution des écarts")
    fig = go.Figure(go.Histogram(x=q.ecart_kwh, nbinsx=45, name="Enedis − DPE",
        marker_color=COULEUR_NEUTRE, marker_line=dict(color="white", width=.5)))
    fig.add_vline(x=0, line_dash="dot", line_color="#273A50")
    fig.update_xaxes(title="Enedis − DPE · " + UNITES[unite][0])
    fig.update_yaxes(title="Observations adresse × année", rangemode="tozero")
    return habiller(fig, "Distribution des écarts")





















def fig_carte(q, stat, dept_selection, mode_selection="click", unite="kwh"):
    fig = carte_complete(q, stat=stat, dept_sel=dept_selection, minimum=2, unite=unite)
    # Explicit mainland bounds avoid switching from auto-fit to world coordinates on zoom.
    fig.update_layout(geo=dict(
        fitbounds=False, center=dict(lon=2.25, lat=46.25),
        lonaxis=dict(range=[-5.8,10.3]), lataxis=dict(range=[41.2,51.5]),
        projection=dict(type="mercator",scale=1.08),
        domain=dict(x=[0,.98],y=[.23,1])),
        margin=dict(l=2,r=52,t=2,b=6))
    return fig






# ---------------------------------------------------------------------------
# Application
def fig_scatter(q, unite="kwh"):
    """Répartition lisible, remplaçant l'ancien nuage de points.

    Frontières incluses dans « proche » : −10 % et +10 %.
    Les deux sources doivent être finies, avec DPE > 0 et Enedis >= 0.
    """
    e, d = "conso_enedis_unifiee_kwh", "conso_dpe_unifiee_kwh"
    base = q.loc[np.isfinite(q[e]) & np.isfinite(q[d]) & q[d].gt(0) & q[e].ge(0)].copy()
    if base.empty:
        return fig_vide("Répartition · aucune comparaison valide")
    seuil = .10
    tolerance = 1e-10  # Évite les erreurs d'arrondi aux frontières ±10 %.
    ratio = (base[e] - base[d]) / base[d]
    inferieur = ratio.lt(-seuil - tolerance)
    superieur = ratio.gt(seuil + tolerance)
    effectifs = [int(inferieur.sum()), int((~inferieur & ~superieur).sum()), int(superieur.sum())]
    parts = [100 * n / len(base) for n in effectifs]
    labels = ["Inférieur au DPE", "Proche du DPE", "Supérieur au DPE"]
    conditions = ["Écart < −10 %", "−10 % ≤ écart ≤ +10 %", "Écart > +10 %"]
    fig = go.Figure(go.Bar(y=labels, x=parts, orientation="h",
        marker_color=[COULEUR_DPE, "#64748B", COULEUR_ENEDIS],
        text=[f"{fmt(v,1)} % · {fmt(n)} observations" for v,n in zip(parts,effectifs)],
        textposition="auto", cliponaxis=True,
        customdata=list(zip(effectifs, conditions)),
        hovertemplate="%{y}<br>%{x:.1f} % · %{customdata[0]} adresses<br>%{customdata[1]}<extra></extra>"))
    fig = habiller(fig, "Adresses : Enedis inférieur, proche ou supérieur au DPE")
    fig.update_layout(showlegend=False, margin=dict(l=135, r=155, t=95, b=50))
    fig.update_xaxes(title="Part des adresses comparables (%)", range=[0,100], ticksuffix=" %", automargin=True)
    fig.update_yaxes(autorange="reversed", showgrid=False, automargin=True)
    return fig

def fig_facteur(q, facteur, unite="kwh"):
    g = resume_facteur(q, facteur)
    if g.empty:
        return fig_vide("Caractéristiques · aucune donnée")
    if facteur == "qualite_isolation":
        ordre = {v:i for i,v in enumerate(["insuffisante", "moyenne", "bonne", "très bonne"])}
        g = g.assign(ordre=g[facteur].map(ordre)).sort_values("ordre")
    elif facteur == "periode_construction":
        ordre = {v:i for i,v in enumerate(["avant 1948", "1948-1974", "1975-1977", "1978-1982",
                     "1983-1988", "1989-2000", "2001-2005", "2006-2012", "2013-2021", "après 2021"])}
        g = g.assign(ordre=g[facteur].map(ordre)).sort_values("ordre")
    fig = go.Figure()
    for col, nom, couleur, motif in [("dpe", "DPE", COULEUR_DPE, "/"), ("enedis", "Enedis", COULEUR_ENEDIS, "")]:
        fig.add_trace(go.Bar(y=g[facteur], x=g[col], orientation="h", name=nom,
            marker_color=couleur, marker_pattern_shape=motif, customdata=g.n,
            hovertemplate="%{y}<br>Médiane %{x:.1f}<br>%{customdata} adresses<extra></extra>"))
    fig.update_layout(barmode="group", margin=dict(l=10, r=10, t=55, b=20))
    fig.update_xaxes(title="Médiane · " + UNITES[unite][0], rangemode="tozero")
    fig.update_yaxes(autorange="reversed")
    return habiller(fig, "DPE et Enedis selon « " + FACTEURS[facteur] + " »", hauteur=max(330, 45 * len(g)))

# Échelle continue : zéro = bleu clair ; maximum affiché = bleu foncé.
# Aucun seuil d'alerte arbitraire et aucune notion de signe pour un écart-type.
PALETTE_DISPERSION = [[0, "#DBEAFE"], [.5, "#6099CE"], [1, "#153859"]]

def marqueur_dispersion(valeurs):
    maximum = float(valeurs.max())
    return dict(color=valeurs, colorscale=PALETTE_DISPERSION,
                cmin=0, cmax=maximum if np.isfinite(maximum) and maximum > 0 else 1,
                showscale=False, line=dict(color="#53718C", width=.6))


def fig_dispersion_facteur(q, facteur, unite="kwh"):
    if q.empty:
        return fig_vide("Dispersion selon les caractéristiques · aucune donnée")
    base = eligibles_dispersion(q).copy()
    base[facteur] = base[facteur].astype(object).fillna("Non renseigné")
    g = resume_facteur(base, facteur)
    g.loc[g.n < 2, "dispersion"] = np.nan
    if g.empty or g.dispersion.notna().sum() == 0:
        return fig_vide("Dispersion · au moins deux adresses par catégorie")
    fig = go.Figure(go.Bar(y=g[facteur], x=g.dispersion, orientation="h",
        marker=marqueur_dispersion(g.dispersion), customdata=g.n, text=[fmt(v,1)+" · n="+str(int(n)) if pd.notna(v) else "Indisponible" for v,n in zip(g.dispersion,g.n)],textposition="auto",
        hovertemplate="%{y}<br>Écart-type %{x:.1f}<br>%{customdata} adresses<extra></extra>"))
    fig.update_xaxes(title="Écart-type · " + UNITES[unite][0] + " · foncé = plus dispersé", rangemode="tozero")
    for _, row in g.loc[g.dispersion.isna()].iterrows():
        fig.add_annotation(x=0, y=row[facteur], text="Non calculable · moins de 2 adresses",
                           showarrow=False, xanchor="left", font=dict(size=10, color="#64748B"))
    fig.update_yaxes(autorange="reversed")
    return habiller(fig, "Variabilité des écarts selon « " + FACTEURS[facteur] + " »", hauteur=max(330, 45 * len(g)))


# Analyses par profil : toutes les colonnes dérivées restent en mémoire.
PROFILE_IDS=["p-surface","p-occupants","p-appareils","p-isolation","p-energie","p-installation","p-type","p-construction"]
PROFILE_COLS=["tranche_surface","occupation_groupe","appareils_groupe","qualite_isolation","energie_chauffage","chauffage_installation","type_logement","periode_construction"]
FACTEURS.update({"classe_dpe":"Classe DPE", "tranche_surface":"Surface", "occupation_groupe":"Nombre d’occupants", "equipements_groupe":"Nombre d’équipements électriques"})
FACTEURS = {k:v for k,v in FACTEURS.items() if k in D.columns and D[k].dropna().nunique()>1}
ANGLE_LABELS={"tranche_surface":"Surface (m²)","occupation_groupe":"Occupants","appareils_groupe":"Appareils"}

def population_facteur(q,facteur):
    """Population commune : ≥ 2 adresses par année, classe et département."""
    # La même base que l’histogramme et le KPI 2 ; aucune exclusion liée
    # à la caractéristique. Les petites catégories restent sans écart-type.
    return eligibles_dispersion(q).copy()


ANGLE_LABELS.update({"type_logement":"Type de logement", "equipements_groupe":"Équipements recensés"})

def figure_angle(q,col,unite,proportions=False):
    if col == "usages_appareils":
        return figures_usages(q, unite)[1 if proportions else 0]
    e,d="conso_enedis_unifiee_kwh","conso_dpe_unifiee_kwh"
    base=q.loc[np.isfinite(q[e])&np.isfinite(q[d])&q[d].gt(0)&q[e].ge(0)].dropna(subset=[col]).copy()
    if base.empty:return fig_vide("Profil · aucune donnée disponible")
    g=base.groupby(col,observed=True).agg(enedis=(e,"mean"),dpe=(d,"mean"),n=("id_adresse_panel","nunique"))
    if col=="tranche_surface": g=g.reindex([t for t in TRANCHES if t in g.index])
    fig=go.Figure()
    if proportions:
        r=(base[e]-base[d])/base[d]
        base["position"]=np.select([r.lt(-.1-1e-10),r.gt(.1+1e-10)],["Inférieur","Supérieur"],default="Proche ±10 %")
        counts=pd.crosstab(base[col],base.position).reindex(g.index).fillna(0)
        for label,color in [("Inférieur",COULEUR_DPE),("Proche ±10 %","#64748B"),("Supérieur",COULEUR_ENEDIS)]:
            n=counts[label] if label in counts else pd.Series(0,index=counts.index)
            pct=100*n/counts.sum(axis=1)
            fig.add_trace(go.Bar(y=g.index.astype(str),x=pct,orientation="h",name=label,marker_color=color,marker_pattern_shape={"Inférieur":"/","Proche ±10 %":"","Supérieur":"x"}[label],
                text=[f"{v:.0f}%" if v>=7 else "" for v in pct],textposition="inside",customdata=np.c_[n,g.n],
                hovertemplate="%{y}<br>%{x:.1f} % · %{customdata[0]:.0f} / %{customdata[1]:.0f} adresses<extra>%{fullData.name}</extra>"))
        fig.update_layout(barmode="stack")
        fig.update_xaxes(range=[0,100],title="Part des adresses (%)")
        title="Adresses proches du DPE selon le profil"
    else:
        for c,label,color,pattern in [("dpe","DPE",COULEUR_DPE,"/"),("enedis","Enedis",COULEUR_ENEDIS,"")]:
            fig.add_trace(go.Bar(y=g.index.astype(str),x=g[c],orientation="h",name=label,marker_color=color,marker_pattern_shape=pattern,
                customdata=np.c_[g.n,g.enedis-g.dpe],hovertemplate="%{y}<br>Moyenne : %{x:.1f}<br>%{customdata[0]:.0f} adresses<br>Écart moyen : %{customdata[1]:+.1f}<extra>%{fullData.name}</extra>"))
        fig.update_layout(barmode="group");fig.update_xaxes(title=UNITES[unite][2],rangemode="tozero")
        title="DPE et Enedis selon le profil"
    fig=habiller(fig,title);fig.update_yaxes(autorange="reversed",automargin=True,title=ANGLE_LABELS[col])
    return fig


def equilibrer_departements(q,depts):
    """Échantillonnage reproductible à effectifs identiques par profil et département.

    Aucune consommation créée. Une strate doit compter au moins deux adresses
    dans chacun des départements. Aucun repli vers les données brutes.
    """
    keys=["annee","nature_donnees","classe_dpe","tranche_surface","energie_chauffage","type_logement","qualite_isolation","periode_construction","chauffage_installation"]
    morceaux=[];n_profils=0
    base=q.dropna(subset=keys)
    # Écarter en une agrégation les profils absents d'un département.
    # Le quota et le tirage restent exactement ceux de la méthode initiale.
    effectifs=base.groupby(keys+["dept_code"],observed=True).id_adresse_panel.nunique().unstack("dept_code",fill_value=0)
    quotas=effectifs.reindex(columns=depts,fill_value=0).min(axis=1)
    admissibles=quotas.loc[quotas.ge(2)].rename("_quota").reset_index()
    base=base.merge(admissibles,on=keys,how="inner",validate="many_to_one")
    for _,g in base.groupby(keys,observed=True,sort=True):
        quota=int(g["_quota"].iloc[0])
        g=g.drop(columns="_quota")
        n_profils+=1
        for dept in depts:
            morceaux.append(g.loc[g.dept_code.eq(dept)].sort_values("id_adresse_panel").sample(n=quota,random_state=2026))
    result=pd.concat(morceaux) if morceaux else q.iloc[:0].copy()
    note=f"Profils équilibrés : {n_profils} profils communs, {len(result)} / {len(q)} observations retenues ; mêmes effectifs par profil/département (tirage fixe). Climat et comportements non contrôlés. "
    return result,note


def figure_departements(q,depts,vue,facteur,unite,agregats=None):
    if not 1<=len(depts)<=5:
        return fig_vide("Choisissez 1 à 5 départements"),"Sélectionnez les départements sur la carte ou dans le filtre."
    if q.empty:return fig_vide("Aucune observation admissible pour cette sélection"),"Pas de valeur de remplacement. Vérifier l’origine, l’année, les départements et le mode équilibré. Les lignes admissibles sont calculées directement à partir du fichier."
    q=q.loc[q.dept_code.isin(depts)].copy()
    if q.annee.nunique()>1:
        return fig_vide("Choisissez une seule année"),"Les années ne sont pas mélangées."
    if q.duplicated(["id_adresse_panel","annee"]).any():
        raise ValueError("Doublons adresse–année dans le calcul territorial")
    g=agregats if agregats is not None else q.groupby("dept_code").agg(n=("id_adresse_panel","nunique"),dpe=("conso_dpe_unifiee_kwh","mean"),enedis=("conso_enedis_unifiee_kwh","mean"),ecart=("ecart_kwh","mean"),dispersion=("ecart_kwh","std"))
    g=g.reindex(depts)
    labels=[f"{d} · {NOMS_DEPT.get(d,d)}" for d in depts]
    counts=[0 if pd.isna(n) else int(n) for n in g.n]
    labels=[f"{label} ({n} adresses)" for label,n in zip(labels,counts)]
    fig=go.Figure()
    if vue=="dept_conso":
        for c,name,color,pattern in [("dpe","DPE",COULEUR_DPE,"/"),("enedis","Enedis",COULEUR_ENEDIS,"")]:
            fig.add_trace(go.Bar(y=labels,x=g[c],orientation="h",name=name,marker_color=color,marker_pattern_shape=pattern,
                hovertemplate="%{y}<br>Moyenne : %{x:.1f}<extra>%{fullData.name}</extra>"))
        fig=make_subplots(rows=1,cols=len(depts),shared_yaxes=True,
            subplot_titles=[f"{d}<br>{n} adresses" for d,n in zip(depts,counts)],horizontal_spacing=.06)
        maximum=float(g[["dpe","enedis"]].max().max())
        for j,d in enumerate(depts,1):
            for c,name,color,pattern in [("dpe","DPE",COULEUR_DPE,"/"),("enedis","Enedis",COULEUR_ENEDIS,"")]:
                value=g.loc[d,c]
                fig.add_trace(go.Bar(x=[name],y=[value],name=name,legendgroup=name,showlegend=j==1,
                    marker_color=color,marker_pattern_shape=pattern,text=[fmt(value,0)],textposition="auto",
                    hovertemplate=NOMS_DEPT.get(d,d)+"<br>"+name+" : %{y:.1f}<extra></extra>"),row=1,col=j)
            fig.update_yaxes(range=[0,maximum*1.18 if maximum>0 else 1],row=1,col=j)
        fig=habiller(fig,"Même échelle · consommation moyenne par département")
        fig.update_yaxes(title_text=UNITES[unite][2],row=1,col=1)
        note="Petits graphiques à échelle commune ; Effectif = adresses distinctes ; une observation par adresse pour l’année sélectionnée. "
        if any(n<10 for n in counts): note+="Moins de 10 adresses : comparaison illustrative. "
        if q.donnee_simulee.any(): note+="Présence de données simulées. "
        return fig,note
        title="DPE et Enedis par département"
        axis=UNITES[unite][2]
    elif vue=="dept_composition":
        if facteur not in q.columns:
            return fig_vide("Caractéristique absente du fichier"),"Aucune valeur n’est générée."
        b=q.copy();b["categorie"]=b[facteur].astype(object).fillna("Non renseigné").astype(str)
        tab=pd.crosstab(b.dept_code,b.categorie).reindex(depts,fill_value=0)
        palette=["#246BB0","#E59842","#205F79","#7F6DA8","#A4644E","#648C99","#6B7280","#BA7395","#839348","#594D75"]
        for i,c in enumerate(tab.columns):
            pct=100*tab[c]/tab.sum(axis=1).replace(0,np.nan)
            fig.add_trace(go.Bar(y=labels,x=pct,orientation="h",name=c,marker_color=palette[i%len(palette)],marker_pattern_shape=["","/","x",".","-"][i%5],text=[f"{c} {v:.0f}%" if v>=12 else "" for v in pct],textposition="inside",
                customdata=tab[c],hovertemplate="%{y}<br>%{x:.1f} % · %{customdata} adresses<extra>%{fullData.name}</extra>"))
        fig.update_layout(barmode="stack");axis="Part des adresses (%)";fig.update_xaxes(range=[0,100])
        title="Profils selon "+FACTEURS.get(facteur,facteur)
    else:
        col="ecart" if vue=="dept_ecart" else "dispersion"
        vals=g[col].where(g.n.ge(2)) if col=="dispersion" else g[col]
        fig.add_trace(go.Bar(y=labels,x=vals,orientation="h",marker=(marqueur_dispersion(vals) if col=="dispersion" else dict(color=["#B66516" if v>0 else "#246BB0" if v<0 else "#64748B" for v in vals])),
            text=[fs(v,1) if col=="ecart" else fmt(v,1) for v in vals],textposition="auto",
            hovertemplate="%{y}<br>%{x:.1f}<extra></extra>"))
        title="Écart moyen Enedis − DPE" if col=="ecart" else "Dispersion des écarts Enedis − DPE"
        axis=UNITES[unite][2];fig.add_vline(x=0,line_color=COULEUR_TEXTE)
    fig=habiller(fig,title);fig.update_yaxes(autorange="reversed",automargin=True)
    fig.update_xaxes(title=axis,rangemode="tozero",automargin=True)
    note="Caractéristiques du DPE associé à chaque adresse, sans inventaire de tous les logements. Même année et mêmes filtres. Effectif = adresses distinctes, pas des logements individuels. Chaque adresse a le même poids.  "
    if any(n<10 for n in counts):note+="Effectifs faibles (<10) : illustration, pas de classement territorial fiable. "
    if vue=="dept_dispersion":note+="Bleu clair → foncé : dispersion croissante, de zéro au maximum affiché ; ce n’est pas une sous/surestimation. Population admissible identique au KPI 2 ; indisponible avec moins de 2 adresses. "
    if q.donnee_simulee.any():note+="Présence de données simulées : les résultats ne démontrent pas un effet réel du territoire."
    return fig,note

def population_affichee(annee,source,dept,classe,unite,vue,facteur,angle,mode,profiles):
    classes=[] if classe=="all" else [classe]
    base=lire(annee,source,[],[],classes,[],unite=unite)
    for col, valeurs in zip(PROFILE_COLS,profiles):
        if valeurs:
            base=base.loc[base[col].astype(str).isin(valeurs)]
            if col in ["occupation_groupe","appareils_groupe"]: base=base.loc[base.donnee_simulee]
    scenario_angle = vue in ["ecart","scatter"] and angle in ["occupation_groupe","appareils_groupe","equipements_groupe","usages_appareils"]
    if scenario_angle: base=base.loc[base.donnee_simulee]
    depts=list(dept or [])
    q=base.loc[base.dept_code.isin(depts)].copy() if depts else base
    info_equilibre=""
    if vue.startswith("dept_") and mode=="equilibre":
        if 2<=len(depts)<=5:
            q,info_equilibre=equilibrer_departements(q,depts)
        else:
            q=q.iloc[:0].copy()
            info_equilibre="Profils équilibrés : sélectionnez de 2 à 5 départements. "
    # Même filtre d’admissibilité pour tous les visuels de dispersion.
    if vue=="dispersion_caracteristiques":
        base=population_facteur(base,facteur)
        q=base.loc[base.dept_code.isin(depts)].copy() if depts else base
    elif vue=="dept_dispersion":
        pass  # Keep all selected addresses; mask std for n < 2 in each department.
    if vue=="histogramme": q=eligibles_dispersion(q)
    return base,q,info_equilibre,scenario_angle,depts

# Interface compacte : trois KPI, une carte, un graphique.
app = Dash(__name__, title="DPE & Enedis · Comparaison", suppress_callback_exceptions=False)
app.index_string = '''<!DOCTYPE html><html lang="fr"><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#273A50;background:#F6F8FB}
.dashboard{height:100dvh;display:flex;flex-direction:column;gap:10px;padding:14px 20px;overflow:hidden}
header h1{font-size:22px;margin:0 0 4px;color:#153859}header p{margin:0;font-size:13px}
.modal{position:fixed;inset:0;background:rgba(15,35,55,.35);z-index:1000;align-items:center;justify-content:center}
.modal-box{background:white;border-radius:12px;padding:24px;width:min(780px,94vw);max-height:90vh;overflow:auto;box-shadow:0 10px 40px #273a5033}.profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-top:18px}
#angle-wrap,#territoire-wrap,#facteur-wrap{font-size:12px;margin-bottom:6px}
.Select--multi .Select-multi-value-wrapper{max-height:40px;overflow-y:auto}
.filters{display:grid;grid-template-columns:.7fr 1.3fr 1.4fr 1fr 1.3fr .9fr;gap:10px;align-items:end}
label{display:block;font-size:12px;margin-bottom:4px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.card,.panel{background:white;border:1px solid #E4EAF1;border-radius:12px;padding:12px;min-width:0}
.card h2{font-size:13px;margin:0 0 7px}.value{font-size:23px;font-weight:bold;color:#153859}.hint{font-size:12px;margin-top:6px;line-height:1.3}
.workspace{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1.15fr;gap:12px}
.panel{display:flex;flex-direction:column;min-height:0}.panel-head{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:13px;min-height:30px}
.plot{flex:1;min-height:0;width:100%}.note{font-size:12px;line-height:1.3;margin-top:5px}
.tabs{display:flex;gap:5px;margin-bottom:4px}.tabs label{display:inline-block;padding:7px;background:#EEF3F9;border-radius:6px;cursor:pointer;margin:0 3px 0 0}
.status{font-size:11px;color:#526174;line-height:1.3}.notice{font-size:11px;color:#674508;background:#FFF4E0;padding:5px 8px;border-radius:6px}
button{cursor:pointer;border:1px solid #CBD5E1;background:white;border-radius:6px;padding:5px 8px;color:#153859}button:focus-visible,input:focus-visible{outline:3px solid #246BB0}
@media(max-width:850px),(max-height:620px){.dashboard{height:auto;min-height:100dvh;overflow:visible}.workspace{grid-template-columns:1fr}.plot{height:360px;flex:none}.filters{grid-template-columns:repeat(3,1fr)}.cards{grid-template-columns:1fr}}
.toolbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;font-size:12px}.journey{font-weight:bold;margin-right:auto;color:#153859}
button{min-height:30px}button:disabled{opacity:.45;cursor:default}*:focus-visible{outline:3px solid #153859;outline-offset:3px}
.tabs label:has(input:checked){background:#153859;color:white}.tabs{flex-wrap:wrap}
.card h2{line-height:1.35}.panel{overflow:auto}.plot{min-height:230px}.note{color:#34465C}
@media(max-height:800px){.dashboard{gap:6px;padding:10px 14px}.value{font-size:20px}.card{padding:9px}.hint{font-size:11px}}
@media(max-width:1100px){.dashboard{height:auto;min-height:100dvh;overflow:visible}.plot{min-height:350px}.workspace{min-height:530px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
.dashboard{padding-left:68px}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}
.sidebar{position:fixed;left:8px;top:14px;z-index:900;width:48px}.sidebar>summary{list-style:none;cursor:pointer;background:#153859;color:#fff;border-radius:10px;padding:12px 8px;width:44px;overflow:hidden;white-space:nowrap;font-size:0}.sidebar>summary::first-letter{font-size:20px}.sidebar>summary:before{content:"☰";font-size:21px}.sidebar[open]{width:295px;bottom:14px;background:#fff;border:1px solid #d4deea;border-radius:12px;box-shadow:4px 6px 24px #273a5030;overflow:auto}.sidebar[open]>summary{width:100%;font-size:14px;padding:14px}.sidebar[open]>summary:before{content:""}.sidebar-content{padding:15px}.sidebar-content h2{font-size:16px}.sidebar .filters{display:flex;flex-direction:column;align-items:stretch;gap:14px}.sidebar .toolbar{display:flex;flex-direction:column;align-items:stretch;margin-top:22px}.sidebar .journey{margin:0 0 8px}.sidebar .Select--multi .Select-multi-value-wrapper{max-height:90px}
.territory-cards{grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:10px 0}.hover-card{text-align:left;padding:10px 8px;min-height:92px;border:1px solid #d5e0ed;border-radius:10px;background:#fff;transition:background .12s}.hover-card strong,.hover-card small,.hover-value{display:block}.hover-card strong{font-size:12px}.hover-value{font-size:13px;font-weight:bold;margin:8px 0}.hover-card small{font-size:10px}.hover-card.active,.hover-card:hover,.hover-card:focus-visible{background:#e7f1fc;border:2px solid #246BB0;padding:9px 7px}.hover-card.active strong:before{content:"▸ "}
.factor-list{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin:7px 0}.factor-item{text-align:left;background:#f1f5f9;border-left:4px solid #b8c9dc;padding:8px;font-size:12px}.factor-item.active,.factor-item:hover{background:#153859;color:white;border-left-color:#E59842}.factor-item.active:before{content:"▸ "}
@media(max-width:850px){.territory-cards{grid-template-columns:1fr 1fr}.dashboard{padding-left:64px}.sidebar[open]{width:min(295px,85vw)}}
.workspace{grid-template-columns:minmax(350px,.9fr) minmax(530px,1.35fr);gap:12px}.left-column,.right-column{display:flex;flex-direction:column;gap:10px;min-height:0;min-width:0}.left-column>.panel{flex:1}.left-column .cards{gap:8px;flex:none}.left-column .card{padding:10px}.left-column .value{font-size:19px}.left-column .card h2{font-size:12px}.right-column>.panel{flex:1;min-height:0}.comparison-pair{display:grid;grid-template-columns:1fr 1fr;flex:1;min-height:0}.comparison-pair .plot{min-height:150px}.variability-panel .plot{min-height:145px}.factor-list{grid-template-columns:repeat(4,1fr);gap:3px;margin:4px 0}.factor-item{padding:5px;font-size:10px}.territory-band{flex:0 0 260px;min-height:260px;position:relative;border-top:3px solid #246BB0}.territory-band .territory-cards{position:absolute;left:340px;right:12px;top:3px;margin:0}.territory-band .hover-card{min-height:58px;padding:5px}.territory-band .hover-value{margin:3px 0}.territory-band .plot{min-height:135px}.territory-band #territoire-wrap{font-size:10px;margin-top:5px;max-width:325px}.territory-band #facteur-wrap{position:absolute;right:15px;top:70px;width:200px;z-index:2}.territory-band small{font-size:10px}.comparison-panel #angle-wrap{max-width:240px;margin:3px 0}.comparison-panel .note{font-size:10px}.dashboard:has(#territory-band[style*="flex"]){height:auto;min-height:100dvh;overflow:visible}.dashboard:has(#territory-band[style*="flex"]) .workspace{min-height:540px}
@media(min-width:1200px) and (min-height:950px){.dashboard:has(#territory-band[style*="flex"]){height:100dvh;overflow:hidden}.dashboard:has(#territory-band[style*="flex"]) .workspace{min-height:0}}
@media(max-width:1100px){.workspace{grid-template-columns:1fr}.right-column>.panel{min-height:360px}.left-column>.panel{min-height:400px}.territory-band{min-height:360px}.territory-band .territory-cards{position:static}.comparison-pair{min-height:250px}}
/* Zone fixe : les changements d’analyse ne modifient jamais la hauteur de page. */
html,body{height:100%;overflow:hidden}
.dashboard,.dashboard:has(#territory-band[style*="flex"]){height:100dvh;min-height:0;overflow:hidden}
.dashboard .workspace,.dashboard:has(#territory-band[style*="flex"]) .workspace{flex:1;min-height:0;grid-template-columns:minmax(0,.9fr) minmax(0,1.35fr)}
.left-column,.right-column{min-height:0;overflow:hidden}.left-column>.panel,.right-column>.panel{min-height:0;overflow:hidden}
.dashboard .plot,.comparison-pair{min-height:0;height:auto;flex:1}.comparison-pair{display:grid}
#territory-band{flex:none;min-height:0;max-height:88px;overflow:hidden}
#territory-band .territory-cards{position:static;margin:0;grid-template-columns:repeat(4,1fr);gap:8px}
#territory-band .hover-card{min-height:64px;padding:7px 10px}.hover-value{margin:4px 0}
#territory-result{flex:1;position:static;min-height:0;border-top:3px solid #246BB0}
#territory-result #territoire-wrap{position:static;max-width:none;margin:10px 0}
#territory-result #facteur-wrap{position:static;width:auto;max-width:280px}
#territory-result .plot{min-height:0;flex:1}
#right-zone.territory-visible>.comparison-panel,#right-zone.territory-visible>.variability-panel{display:none}
#right-zone.territory-visible>#territory-result{display:flex!important}
#retour-general{align-self:flex-start;margin-bottom:10px}
@media(max-height:800px){.dashboard{gap:5px}header h1{font-size:18px}.factor-item{font-size:10px;padding:3px}.left-column .value{font-size:16px}.left-column .hint{font-size:10px}.notice,.status{font-size:10px}.panel{padding:8px}}

.zoom-heading{display:flex;justify-content:space-between;align-items:center;width:100%;text-align:left;border:0;background:transparent;padding:4px 0;flex:none}
.zoom-hint{font-size:11px;font-weight:normal;margin-left:12px;color:#246BB0}
#right-zone>.panel.section-zoomed{display:flex!important;position:fixed;inset:18px;z-index:1500;min-height:0;width:auto;height:auto;margin:0;padding:24px;background:white;border:2px solid #246BB0;border-radius:14px;box-shadow:0 0 0 100vmax #10223899;animation:section-zoom-in .18s ease-out;overflow:hidden}
.section-zoomed .zoom-heading{font-size:22px;margin-bottom:14px}.section-zoomed .zoom-hint{font-size:14px}
.section-zoomed .comparison-pair,.section-zoomed .plot{flex:1;min-height:0}
.section-zoomed .factor-item{font-size:14px;padding:10px}.section-zoomed .note,.section-zoomed small{font-size:14px}
@keyframes section-zoom-in{from{transform:scale(.96);opacity:.75}to{transform:scale(1);opacity:1}}
@media(prefers-reduced-motion:reduce){#right-zone>.panel.section-zoomed{animation:none}}

body{background:#eaf0f6}.dashboard{background:linear-gradient(145deg,#f4f7fb 0%,#eaf0f6 100%)}
.card,.panel{border:1px solid #d5e0eb;box-shadow:0 2px 6px #193c5c08}.card{border-top:3px solid #246BB0}
.dashboard .workspace{grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:12px}
.dashboard:has(#territory-band[style*="flex"]) .workspace{grid-template-columns:minmax(0,1fr) minmax(0,1.2fr)}
.sidebar{top:50%;left:8px;transform:translateY(-50%);width:44px;bottom:auto}
.sidebar>summary{font-size:24px;width:44px;text-align:center;padding:13px 6px;line-height:1.2}
.sidebar>summary:before{content:none}.sidebar>summary::first-letter{font-size:24px}
.sidebar[open]{top:14px;bottom:14px;transform:none;width:295px}.sidebar[open]>summary{font-size:24px;text-align:right}
.panel-head{border-bottom:1px solid #e6edf4;padding-bottom:5px}.zoom-heading{border-bottom:1px solid #e6edf4;padding-bottom:6px}
.factor-item{transition:background-color .1s ease,border-color .1s ease}.factor-item.active{border-left-width:4px}
#map{cursor:grab}#map:active{cursor:grabbing}.hover-card.active{border-left:4px solid #246BB0}
@media(prefers-reduced-motion:reduce){.factor-item,.hover-card{transition:none}}

#menu-lateral:not([open]){position:fixed!important;left:8px!important;top:50%!important;bottom:auto!important;width:44px!important;height:48px;transform:translateY(-50%)!important;overflow:visible;z-index:1200}
#menu-lateral>summary{display:block!important;position:static!important;width:44px!important;height:48px!important;font-size:26px!important;line-height:32px!important;text-indent:0!important;padding:8px 4px!important;color:#fff!important;overflow:visible!important;transform:none!important}
#menu-lateral[open]>summary{width:100%!important;text-align:right}#menu-lateral>summary::before,#menu-lateral>summary::after{content:none!important}
#menu-lateral>summary::-webkit-details-marker{display:none}

/* Questions métier : même encodage et espace réservé, sans déplacement au clic. */
.business-question,.zoom-heading{color:#153859;background:#EEF4FA;border:0;border-left:4px solid #D97706;border-radius:7px;padding:9px 11px;line-height:1.3}
header h1.general-question{font-size:22px;margin:0 125px 5px 0;padding:7px 12px;font-weight:700}
.zoom-heading{font-size:16px;gap:8px;min-height:64px}.zoom-heading strong{flex:1}.zoom-heading .zoom-hint{font-size:11px;flex:none;white-space:nowrap}
.map-question-head{height:86px;min-height:86px;border:0;padding:0;align-items:center}
.map-question-toggle{display:flex;align-items:center;flex:1;min-width:0;height:80px;text-align:left;font-size:16px;font-weight:700;cursor:pointer}
.map-business-question{display:none}.map-question-toggle[aria-expanded="true"] .map-business-question{display:block}.map-question-toggle[aria-expanded="true"] .map-prompt{display:none}
#map-panel{cursor:default}#map-question-toggle:hover{background:#e1edf8}#map-question-toggle:focus-visible{outline:3px solid #153859;outline-offset:2px}
.section-zoomed .zoom-heading{font-size:22px;min-height:70px}
@media(max-height:800px){header h1.general-question{font-size:19px}.zoom-heading,.map-question-toggle{font-size:14px}.zoom-heading{min-height:55px}.map-question-head{height:76px;min-height:76px}.map-question-toggle{height:70px}}

/* Gestalt : une région commune, deux étapes alignées, sans ajouter de hauteur. */
#right-zone:not(.territory-visible){
    background:#fff;border:1px solid #B9CBDD;border-radius:16px;
    box-shadow:0 3px 12px #1538590A;padding:8px;gap:0;
    min-height:0;min-width:0;
}
#right-zone:not(.territory-visible)>.panel:not(.section-zoomed){
    border:0;border-radius:0;box-shadow:none;background:transparent;
    padding:8px;min-height:0;min-width:0;
}
#right-zone:not(.territory-visible)>.variability-panel:not(.section-zoomed){
    border-top:1px solid #CAD8E5;padding-top:10px;
}
#right-zone:not(.territory-visible) .zoom-heading{
    background:#EEF4FA;color:#153859;border-left:4px solid #D97706;
    text-align:left;border-radius:7px;line-height:1.3;
}
#right-zone .zoom-heading:hover{background:#E2EDF7}
#right-zone .zoom-heading:focus-visible{outline:3px solid #246BB0;outline-offset:2px}
@media(max-height:800px){
    #right-zone:not(.territory-visible){padding:5px}
    #right-zone:not(.territory-visible)>.panel:not(.section-zoomed){padding:6px}
}

.workspace{grid-template-columns:minmax(390px,1.08fr) minmax(530px,1.25fr)!important}
#map{flex:1;min-height:0}.dpe-radios{display:flex;flex-wrap:wrap;gap:8px}
.dpe-radios label{border:1px solid #c5d1df;border-radius:6px;padding:7px;cursor:pointer}
.dpe-radios label:has(input:checked){background:#e3effb;border-color:#246bb0;font-weight:700}
#menu-lateral>summary{transition:background-color .15s;cursor:pointer}
#menu-lateral>summary:hover,#menu-lateral>summary:focus-visible,#menu-lateral[open]>summary{background:#246bb0!important}
#facteur-wrap{position:relative;z-index:30}.Select-menu-outer{z-index:1000!important}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}

.angle-buttons{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:5px}
.angle-buttons label{display:flex;align-items:center;gap:6px;min-height:38px;padding:7px 10px;border:1px solid #b7c9dc;border-radius:5px;background:#f1f5f9;color:#153859;font-size:15px;cursor:pointer;box-sizing:border-box}
.angle-buttons label:has(input:checked){background:#153859;color:white;border-left:4px solid #e69a38}
.angle-buttons label:hover{border-color:#e69a38}
.angle-buttons input{accent-color:#e69a38}
.angle-buttons label:focus-within{outline:2px solid #e69a38;outline-offset:2px}
.sidebar{left:0;top:0;bottom:0;height:100dvh;transform:none;width:48px;background:#e6edf5;border-right:1px solid #b7c9dc;display:flex;align-items:center}
.sidebar>summary{width:48px;box-sizing:border-box;padding:16px 2px;letter-spacing:-3px;font-size:30px;border-radius:0 8px 8px 0;transition:background .15s}
.sidebar>summary:hover,.sidebar>summary:focus-visible{background:#ad641d;color:white}
.sidebar>summary:before{content:none}
.sidebar[open]{left:0;top:0;bottom:0;height:100dvh;transform:none;width:295px;display:block;border-radius:0;overflow:auto}
.sidebar[open]>summary{width:100%;background:#ad641d}
@media(max-width:900px){.angle-buttons{grid-template-columns:repeat(2,minmax(0,1fr))}}

.comparison-panel #angle-wrap{max-width:none;width:100%;flex:none;margin:4px 0 6px}
.angle-hover-buttons{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;width:100%}
.angle-hover-button{min-width:0;min-height:36px;padding:7px 5px;border:1px solid #b7c9dc;border-radius:5px;background:#f1f5f9;color:#153859;font:600 13px/1.2 Arial,sans-serif;white-space:normal;overflow-wrap:normal;cursor:pointer;transition:background-color .1s}
.angle-hover-button[aria-pressed="true"],.angle-hover-button:hover{background:#153859;color:white;border-color:#153859;box-shadow:inset 3px 0 #e69a38}
.angle-hover-button:focus-visible{outline:2px solid #e69a38;outline-offset:2px}
.angle-caption{font-size:13px;margin-bottom:5px}
@media(max-width:600px){.angle-hover-buttons{grid-template-columns:repeat(3,minmax(0,1fr))}}

.comparison-chart{display:flex;flex-direction:column;min-width:0;min-height:0}
.comparison-chart-title{font:600 14px/1.4 Arial,sans-serif;color:#153859;padding:4px 8px;flex:none}
.comparison-pair{column-gap:16px}
.comparison-chart .plot{flex:1;min-height:0}

.variability-panel .factor-list{grid-template-columns:repeat(4,minmax(0,1fr));gap:5px}
.variability-panel .factor-item{font-size:13px;line-height:1.3;padding:8px;min-height:36px}
.variability-panel .factor-item:focus-visible{outline:2px solid #e59842;outline-offset:2px}

.chart-caption{flex:none;font:600 13px/1.35 Arial,sans-serif;color:#173b5c;padding:5px 8px;border-top:1px solid #dce5ef;min-height:38px}
.zero-reference{flex:none;padding:6px 12px;border-left:4px solid #246BB0;background:#eaf2fa;color:#153859;font:700 15px/1.3 Arial,sans-serif}
.profile-buttons{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}
.profile-hover-button{border:1px solid #b8cadd;border-radius:7px;background:#f5f8fc;color:#173b5c;padding:7px 10px;font-size:13px;cursor:pointer}
.profile-hover-button:hover,.profile-hover-button:focus-visible,.profile-hover-button[aria-pressed="true"]{background:#dfedfa;border-color:#246BB0;outline:2px solid #246BB0;outline-offset:1px}
#territory-result #facteur-wrap{max-width:none;width:100%;flex:none}
#territory-note{flex:none;line-height:1.35;font-size:12px;max-height:76px;overflow:auto}
#territory-result{min-width:0;gap:6px}
.comparison-pair{gap:10px}.comparison-chart-title{min-height:24px}
@media(max-height:750px){.chart-caption{font-size:12px;min-height:30px}.profile-hover-button{padding:4px 7px}.zero-reference{font-size:13px;padding:4px 8px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}

</style></head><body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer><script>
(function(){let active=null,previous=null;
let lastView=null,lastFactor=null;
function reveal(event){const button=event.target.closest('[data-view],[data-factor]');if(!button)return;
if(event.type==='pointerover'&&button.contains(event.relatedTarget))return;
const v=button.dataset.view,f=button.dataset.factor;
if(v&&window.dash_clientside?.set_props){if(event.type==='click'){window.territoryPinned=true;}else if(window.territoryPinned){return;}window.dash_clientside.set_props('territory-open',{data:true});if(!button.classList.contains('active'))window.dash_clientside.set_props('vue',{value:v});}
if(f&&!button.classList.contains('active')&&window.dash_clientside?.set_props){window.dash_clientside.set_props('facteur',{value:f});window.dash_clientside.set_props('variability-view',{value:'caracteristiques'});}}
document.addEventListener('pointerdown',e=>{if(e.target.closest('#facteur-wrap,.Select-menu-outer'))window.profileInteractionUntil=Date.now()+600;},true);
document.addEventListener('click',e=>{
 const zone=document.getElementById('right-zone');if(!zone?.classList.contains('territory-visible'))return;
 if(e.target.closest('#territory-result,#territory-band,#map,#menu-lateral,.modal,.section-zoomed,.Select-menu-outer,.Select-option,[role=option],[role=listbox],.dash-dropdown'))return;
 if(window.profileInteractionUntil>Date.now())return;
 window.territoryPinned=false;
 window.dash_clientside?.set_props('territory-open',{data:false});
 window.dash_clientside?.set_props('dept',{value:[]});
});
// Ctrl + molette agit uniquement sur la projection principale de la carte.
let mapZoomFrame=null,mapZoomScale=null,mapZoomBusy=false;
document.addEventListener('wheel',e=>{
 if(!e.ctrlKey || !e.target.closest('#map'))return;
 const plot=document.querySelector('#map .js-plotly-plot');
 if(!plot||!window.Plotly||!plot._fullLayout?.geo)return;
 e.preventDefault();e.stopPropagation();
 const current=Number(mapZoomScale ?? plot._fullLayout.geo.projection.scale ?? 1.08);
 const delta=Math.max(-120,Math.min(120,e.deltaY));
 mapZoomScale=Math.max(.85,Math.min(5,current*Math.exp(-delta*.0015)));
 function applyZoom(){
   mapZoomFrame=null;
   if(mapZoomBusy){mapZoomFrame=requestAnimationFrame(applyZoom);return;}
   const requested=mapZoomScale;
   mapZoomBusy=true;
   Promise.resolve(window.Plotly.relayout(plot,{'geo.projection.scale':requested}))
     .finally(()=>{mapZoomBusy=false;});
 }
 if(!mapZoomFrame)mapZoomFrame=requestAnimationFrame(applyZoom);
},{passive:false,capture:true});
document.addEventListener('pointerover',reveal);document.addEventListener('focusin',reveal);document.addEventListener('click',reveal);

const visible=()=>Array.from(document.querySelectorAll('.modal')).find(e=>getComputedStyle(e).display!=='none');
new MutationObserver(()=>{const m=visible();if(m!==active){if(m){previous=document.activeElement;active=m;setTimeout(()=>m.querySelector('button')?.focus(),0);}else{active=null;previous?.focus();}}}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['style']});
document.addEventListener('keydown',e=>{if(!active)return;if(e.key==='Escape'){active.querySelector('button')?.click();return;}if(e.key==='Tab'){const items=Array.from(active.querySelectorAll('button,input,[tabindex="0"]')).filter(x=>!x.disabled&&x.getClientRects().length);const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}});})();

(function(){
let zoomed=null,trigger=null;
function resize(){requestAnimationFrame(()=>{window.dispatchEvent(new Event('resize'));});}
function closeZoom(){if(!zoomed)return;
 zoomed.classList.remove('section-zoomed');zoomed.removeAttribute('role');zoomed.removeAttribute('aria-modal');zoomed.removeAttribute('aria-label');
 trigger?.setAttribute('aria-expanded','false');
 const hint=trigger?.querySelector('.zoom-hint');if(hint)hint.textContent=' ⛶ Agrandir';
 zoomed=null;trigger?.focus({preventScroll:true});resize();
}
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-zoom="section"]');if(!b)return;
 const panel=b.closest('.panel');if(zoomed===panel){closeZoom();return;}
 closeZoom();zoomed=panel;trigger=b;
 panel.classList.add('section-zoomed');panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');panel.setAttribute('aria-label',b.querySelector('strong').textContent);
 b.setAttribute('aria-expanded','true');b.querySelector('.zoom-hint').textContent=' ✕ Réduire · Échap';b.focus({preventScroll:true});resize();
});
document.addEventListener('keydown',e=>{
 if(!zoomed)return;
 if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();closeZoom();return;}
 if(e.key==='Tab'){
 const items=Array.from(zoomed.querySelectorAll('button,input,[tabindex="0"]')).filter(x=>!x.disabled&&x.getClientRects().length);
 const first=items[0],last=items[items.length-1];
 if(e.shiftKey&&(document.activeElement===first||!zoomed.contains(document.activeElement))){e.preventDefault();last?.focus();}
 else if(!e.shiftKey&&(document.activeElement===last||!zoomed.contains(document.activeElement))){e.preventDefault();first?.focus();}
 }
},true);
})();

(function(){
function toggleQuestion(){const b=document.getElementById('map-question-toggle');if(!b)return;
 b.setAttribute('aria-expanded',b.getAttribute('aria-expanded')==='true'?'false':'true');}
document.addEventListener('click',e=>{
 const panel=document.getElementById('map-panel');if(!panel||!panel.contains(e.target))return;
 if(e.target.closest('#map-question-toggle')){toggleQuestion();return;}
 if(e.target===panel||e.target.classList.contains('map-question-head'))toggleQuestion();
});
})();



</script><script>
(function(){
 function choose(event){
   const button=event.target.closest && event.target.closest('.angle-hover-button');
   if(!button)return;
   if(event.type==='mouseover' && button.contains(event.relatedTarget))return;
   if(button.getAttribute('aria-pressed')==='true')return;
   if(!window.dash_clientside || !window.dash_clientside.set_props)return;
   document.querySelectorAll('.angle-hover-button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
   clearTimeout(window.angleHoverTimer);
   window.dash_clientside.set_props('angle',{value:button.dataset.angle});
 }
 document.addEventListener('mouseover',choose);
 document.addEventListener('focusin',choose);
 document.addEventListener('click',choose);
})();



</script><script>
document.addEventListener('mouseout',function(e){
 const b=e.target.closest?.('.angle-hover-button');
 if(!b || b.contains(e.relatedTarget))return;
 if(e.relatedTarget?.closest?.('.angle-hover-button'))return;
 clearTimeout(window.angleHoverTimer);
 window.dash_clientside?.set_props('angle',{value:'classe_dpe'});
});
document.addEventListener('pointerout',function(e){
 const b=e.target.closest?.('[data-factor]');
 if(!b || b.contains(e.relatedTarget))return;
 if(e.relatedTarget?.closest?.('[data-factor]'))return;
 window.dash_clientside?.set_props('variability-view',{value:'distribution'});
});




(function(){
function activateProfile(e){const b=e.target.closest?.('[data-profile]');if(!b)return;
 if(e.type==='pointerover'&&b.contains(e.relatedTarget))return;
 window.territoryPinned=true;
 window.dash_clientside?.set_props('territory-open',{data:true});
 window.dash_clientside?.set_props('vue',{value:'dept_composition'});
 window.dash_clientside?.set_props('facteur',{value:b.dataset.profile});}
 ['pointerover','focusin','click'].forEach(event=>document.addEventListener(event,activateProfile));
})();
</script></body></html>'''

def champ(label, component):
    return html.Div([html.Label(label, htmlFor=component.id), component])

def carte_kpi(titre, valeur, note, couleur="#153859"):
    return html.Div([html.H2(titre),html.Div(valeur,className="value",style={"color":couleur}),html.Div(note,className="hint")],className="card",style={"borderLeft":"4px solid "+couleur})

app.layout=html.Main(className="dashboard",children=[
    dcc.Store(id="historique",data={"past":[],"present":["2024","all",[],"all","kwh","F→E","ecart_moyen","qualite_isolation","type_logement","brut"]+[[] for _ in PROFILE_IDS],"future":[]}),
    dcc.Download(id="export-csv"),
    html.Header([html.H1("Dans quelle mesure les estimations DPE correspondent-elles aux consommations électriques Enedis ?",className="business-question general-question"),html.Span()]),
    html.Div(className="filters",children=[
        champ("Année",dcc.Dropdown(id="annee",value="2024",clearable=False,options=[{"label":x,"value":x} for x in ["2023","2024"]])),
        dcc.Input(id="source",value="all",type="hidden"),
        champ("Départements",dcc.Dropdown(id="dept",value=[],multi=True,options=[{"label":f"{d} · {NOMS_DEPT.get(d,'')}","value":d} for d in DEPTS_DONNEES],placeholder="Tous les départements disponibles")),
        champ("Classe DPE",dcc.RadioItems(id="classe",value="all",className="dpe-radios",options=[{"label":"Toutes","value":"all"}]+[{"label":c,"value":c} for c in CLASSES])),
        champ("Unité",dcc.Dropdown(id="unite",value="kwh",clearable=False,options=[{"label":"kWh/logement/an","value":"kwh"},{"label":"kWh/m²/an","value":"m2"}])),
        champ("Classes comparées",dcc.Dropdown(id="transition",value="F→E",clearable=False,options=[{"label":a+" → "+b,"value":a+"→"+b} for a,b in zip("GFEDCB","FEDCBA")]))]),
    html.Div(id="profils-modal",style={"display":"none"},className="modal",children=[
        html.Section(className="modal-box",role="dialog",**{"aria-modal":"true","aria-label":"Filtres de profils et usages"},children=[
            html.Div([html.Strong("Profils & usages"),html.Button("Fermer",id="fermer-profils",n_clicks=0,style={"float":"right"})]),
            html.P("Ces filtres s’appliquent à la carte, aux deux KPI et aux graphiques. Occupation et appareils : données simulées uniquement.",className="note"),
            html.Div(className="profile-grid",children=[
                html.Div(champ(n,dcc.Dropdown(id=i,multi=True,options=[{"label":str(v),"value":str(v)} for v in sorted(D[c].dropna().astype(str).unique()) if str(v)!="Non mesurée"],placeholder="Tous")), style={"display":"none"} if i=="p-appareils" else {})
                for i,c,n in [("p-surface","tranche_surface","Surface (m²)"),("p-occupants","occupation_groupe","Nombre d’occupants · simulé"),
                    ("p-appareils","appareils_groupe","Consommation des appareils · simulée"),("p-isolation","qualite_isolation","Isolation"),
                    ("p-energie","energie_chauffage","Énergie de chauffage"),("p-installation","chauffage_installation","Installation de chauffage"),
                    ("p-type","type_logement","Type de logement"),("p-construction","periode_construction","Période de construction")]]),
            html.P("Eau chaude : pas de type d’installation documenté dans le fichier. Les ratios par m² sont indisponibles pour les sources originales : surface proxy non concordante.",className="note"),
            html.Button("Effacer ces filtres",id="effacer-profils",n_clicks=0)])]),
    html.Div(className="toolbar",children=[
        html.Span("Explorer → comparer → vérifier",className="journey"),
        html.Button("← Annuler les filtres",id="undo",disabled=True,n_clicks=0),
        html.Button("Rétablir →",id="redo",disabled=True,n_clicks=0),
        html.Button(id="ouvrir-details",n_clicks=0,style={"display":"none"}),
        html.Button(id="exporter",n_clicks=0,style={"display":"none"}),
        html.Button("Exporter en PDF",id="export-pdf",n_clicks=0),
        html.Span(id="pdf-status",role="status"),
        html.Span(id="history-status",className="status",role="status")]),
    html.Div(id="details-modal",className="modal",style={"display":"none"},children=[
        html.Section(className="modal-box",role="dialog",**{"aria-modal":"true","aria-label":"Valeurs de la sélection"},children=[
            html.Button("Fermer",id="fermer-details",n_clicks=0),html.H2("Vérifier les données affichées"),
            html.P(id="details-resume"),
            dash_table.DataTable(id="details-table",page_size=10,sort_action="native",filter_action="native",
                style_table={"overflowX":"auto"},style_cell={"textAlign":"left","fontFamily":"Arial","fontSize":13,"maxWidth":240,"whiteSpace":"normal"},
                style_header={"fontWeight":"bold","backgroundColor":"#EEF3F9"}),
            html.P("Tableau paginé des observations retenues. L’export contient toute cette sélection et ses indicateurs d’origine.",className="note")])]),
    html.Div(id="cards",className="cards",role="status",**{"aria-live":"polite"}),
    html.Div(className="workspace",children=[
        html.Section(className="panel",children=[
            html.Div(className="panel-head map-question-head",children=[
                html.Button([
                    html.Span("Comparer les départements ›",className="map-prompt"),
                    html.Strong("Les écarts entre Enedis et DPE sont-ils similaires d’un département à l’autre ?",className="map-business-question",id="map-question-text")],
                    id="map-question-toggle",className="business-question map-question-toggle",title="Afficher ou masquer la question départementale",
                    **{"aria-expanded":"false","aria-controls":"map-question-text"}),
                html.Button("Effacer les départements",id="reset",n_clicks=0)]),
            dcc.RadioItems(id="stat",value="ecart_moyen",inline=True,options=[{"label":" Écart moyen  ","value":"ecart_moyen"},{"label":" Écart-type","value":"ecart_type"}],style={"fontSize":"12px","margin":"6px 0"}),
            dcc.Graph(id="map",className="plot",responsive=True,config={"displayModeBar":True,"modeBarButtonsToAdd":["zoomInGeo","zoomOutGeo","resetGeo"],"scrollZoom":False,"displaylogo":False,"topojsonURL":"/assets/"}),
            html.Div("Cliquez pour sélectionner · Ctrl + molette : zoom · Gris : absent ; beige : effectif insuffisant.",className="note")]),
        html.Section(className="panel",children=[
            dcc.Dropdown(id="rubrique",value="comparaison",clearable=False,options=[
                {"label":"1 · Comparer Enedis et DPE","value":"comparaison"},
                {"label":"2 · Comprendre la variabilité","value":"variabilite"},
                {"label":"3 · Comparer les départements","value":"territoires"}]),
            dcc.RadioItems(id="vue",value="ecart",inline=True,className="tabs",
                options=[{"label":"Consommations par classe","value":"ecart"},{"label":"Proportions des adresses","value":"scatter"}],style={"marginTop":"8px"}),
            html.Div(id="angle-wrap",children=[
                html.Div("Comparer selon",id="angle-caption",className="angle-caption"),
                dcc.Input(id="angle",value="classe_dpe",type="text",style={"display":"none"}),
                html.Div([
                    html.Button(label,type="button",className="angle-hover-button",
                        **{"data-angle":value,"aria-pressed":"true" if value=="classe_dpe" else "false"})
                    for value,label in [
                        ("type_logement","Type de logement"),
                        ("usages_appareils","Appareils électriques"),("tranche_surface","Surface"),
                        ("occupation_groupe","Occupants")]
                ],className="angle-hover-buttons",role="group",**{"aria-label":"Comparer selon"})
            ]),
            html.Div(id="territoire-wrap",style={"display":"none"},children=[
                dcc.RadioItems(id="mode-territoire",value="brut",inline=True,options=[{"label":" Échantillons bruts","value":"brut"},{"label":" Profils équilibrés","value":"equilibre"}]),
                html.Small("Brut : toutes les adresses filtrées. Équilibré : mêmes effectifs dans les profils communs, sans créer de données (2 à 5 départements)."),html.Button("Exemple à vérifier : Var / Hauts-de-Seine",id="exemple-original",n_clicks=0,style={"marginLeft":"8px","fontSize":"11px"})]),
            html.Div(id="facteur-wrap",style={"display":"none"},children=[
                html.Strong("Caractéristique à explorer"),
                dcc.Input(id="facteur",value="qualite_isolation",type="text",style={"display":"none"}),
                html.Div([html.Button(label,className="profile-hover-button",**{"data-profile":key})
                    for key,label in FACTEURS.items()],className="profile-buttons")]),
            dcc.Graph(id="graph",className="plot",responsive=True,config={"displayModeBar":True,"displaylogo":False,"modeBarButtonsToRemove":["lasso2d","select2d"],"toImageButtonOptions":{"format":"png","filename":"comparaison_dpe_enedis"}}),
            html.Div(id="lecture",style={"display":"none"},className="note",role="status",**{"aria-live":"polite"})])]),
    html.Div(id="effectifs",style={"display":"none"}),
    html.Div(style={"display":"none"})])

# Navigation latérale native : clic pour ouvrir / fermer, clavier compatible.
children=app.layout.children
filters=next(x for x in children if getattr(x,"className",None)=="filters")
toolbar=next(x for x in children if getattr(x,"className",None)=="toolbar")
children.remove(filters);children.remove(toolbar)
# Le changement de classe n'est plus une analyse proposée ; conserver seulement
# sa valeur technique pour la compatibilité des callbacks existants.
filters.children[-1].style={"display":"none"}
sidebar=html.Details(id="menu-lateral",className="sidebar",open=False,children=[
    html.Summary("›››",title="Ouvrir ou fermer les filtres et outils",**{"aria-label":"Ouvrir ou fermer le menu"}),
    html.Div([html.H2("Votre sélection"),filters,toolbar],className="sidebar-content")])
children.insert(2,sidebar)
workspace=next(x for x in children if getattr(x,"className",None)=="workspace")
right=workspace.children[1]
TECH_FACTEURS={k:FACTEURS[k] for k in ["qualite_isolation","periode_construction","type_logement","tranche_surface"]}
hover_factors=html.Div(id="factor-hover",style={"display":"none"},children=[
    
    html.Div([html.Button(label,id="hover-"+key,className="factor-item",**{"data-factor":key}) for key,label in TECH_FACTEURS.items()],className="factor-list")])
territory_cards=html.Div(id="territory-cards",className="territory-cards",style={"display":"none"})
right.children.insert(2,territory_cards)
right.children.insert(-2,hover_factors)

# Deux colonnes stables : synthèse et carte à gauche, analyses à droite.
left=workspace.children[0]
left.id="map-panel"
cards=next(x for x in children if getattr(x,"id",None)=="cards")
children.remove(cards)
left_column=html.Div([cards,left],className="left-column")
def take(identifier):
    component=next(x for x in right.children if getattr(x,"id",None)==identifier)
    right.children.remove(component)
    return component
comparison_graph=take("graph");comparison_note=take("lecture")
comparison_graph.config={"displayModeBar":False,"responsive":True}
angle_controls=take("angle-wrap");factor_controls=take("facteur-wrap")
territory_controls=take("territoire-wrap")
right.children.remove(hover_factors);right.children.remove(territory_cards)

# Réglages déplacés hors de la vue principale, sans changer les calculs.
map_stat=next(c for c in left.children if getattr(c,"id",None)=="stat")
left.children.remove(map_stat)
# Même identifiant et valeurs qu'avant ; présentation compacte dans le menu.
map_stat=dcc.Dropdown(id="stat",value="ecart_moyen",clearable=False,options=[
    {"label":"Écart moyen","value":"ecart_moyen"},
    {"label":"Écart-type","value":"ecart_type"}])
territory_controls.children=[
    champ("Population comparée",dcc.Dropdown(id="mode-territoire",value="brut",clearable=False,
        options=[{"label":"Toutes les adresses filtrées","value":"brut"},
                 {"label":"Profils communs équilibrés","value":"equilibre"}])),
    html.Details([html.Summary("Exemple de sélection"),
        html.Button("Var et Hauts-de-Seine",id="exemple-original",n_clicks=0)])]
sidebar.children[1].children.append(html.Details([
    html.Summary("Options d’analyse"),
    champ("Indicateur cartographique",map_stat),
    html.Button("Filtres des logements",id="ouvrir-profils",n_clicks=0),
    territory_controls],style={"marginTop":"16px"}))
# Ancien sélecteur de rubrique conservé hors affichage pour les callbacks.
right.style={"display":"none"}
children.append(right)
comparison=html.Section(className="panel comparison-panel",children=[
    html.Button([html.Strong("Enedis indique-t-il une consommation inférieure, proche ou supérieure à l’estimation DPE ?"),html.Span(" ⛶ Agrandir",className="zoom-hint")],className="zoom-heading",title="Agrandir cette section · Échap pour revenir",**{"data-zoom":"section","aria-expanded":"false"}),angle_controls,
    html.Div([
        html.Div([html.Div("Consommation moyenne",className="comparison-chart-title"),comparison_graph,html.Div(id="comparison-left-caption",className="chart-caption",role="status")],className="comparison-chart"),
        html.Div([html.Div("Enedis proche du DPE ?",className="comparison-chart-title"),
            dcc.Graph(id="proportions-graph",responsive=True,config={"displayModeBar":False},className="plot"),html.Div(id="comparison-right-caption",className="chart-caption",role="status")],className="comparison-chart")
    ],className="comparison-pair"),comparison_note])
variability=html.Section(className="panel variability-panel",children=[
    html.Button([html.Strong("L’écart moyen cache-t-il de grandes différences entre les adresses ?"),html.Span(" ⛶ Agrandir",className="zoom-hint")],className="zoom-heading",title="Agrandir cette section · Échap pour revenir",**{"data-zoom":"section","aria-expanded":"false"}),
    dcc.Input(id="variability-view",value="distribution",type="text",style={"display":"none"}),
    hover_factors,dcc.Graph(id="variability-graph",responsive=True,config={"displayModeBar":False},className="plot"),
    html.Div(id="zero-reference",className="zero-reference",children="Zéro signifie Enedis = DPE"),
    html.Div(id="variability-caption",className="chart-caption",role="status")])
workspace.children=[left_column,html.Div([comparison,variability],className="right-column",role="group",**{"aria-label":"Comprendre les écarts Enedis et DPE : niveau moyen et variabilité entre les adresses"})]
territory_band=html.Section(id="territory-band",className="panel territory-band",style={"display":"none"},children=[
    html.Strong("Comparer les départements · sélection sur la carte"),territory_cards,
    factor_controls,
    html.Div(id="territory-graph-host",className="plot",style={"minHeight":0,"display":"flex","flexDirection":"column"}),
    html.Small(id="territory-note")])
# La bande du bas ne contient que les commandes ; le résultat occupe la droite.
territory_band.children.remove(territory_cards)
territory_band.id="territory-result"
territory_band.style={"display":"none"}

workspace.children[1].id="right-zone"
workspace.children[1].children.append(territory_band)
children.insert(children.index(workspace)+1,html.Div(id="territory-band",style={"display":"none"},children=[territory_cards]))
children.append(dcc.Store(id="territory-open",data=False))
children.append(dcc.Store(id="variability-cache"))
children.append(dcc.Store(id="comparison-cache"))
children.append(dcc.Store(id="territory-cache"))

@app.callback(Output("dept","value"),Input("map","clickData"),Input("reset","n_clicks"),State("dept","value"),prevent_initial_call=True)
def selectionner(clic,n,actuel):
    from dash import ctx
    if ctx.triggered_id=="reset": return []
    points=(clic or {}).get("points",[])
    code=str(points[0].get("location","")).zfill(2) if points else ""
    if code not in TOUS_DEPT: raise PreventUpdate
    selection=list(actuel or [])
    if code in selection: selection.remove(code)
    else: selection.append(code)
    return selection

from functools import lru_cache, wraps
from copy import deepcopy

def memoiser_affichage(function):
    def freeze(value):
        if isinstance(value,(list,tuple)):
            return tuple(freeze(v) for v in value)
        return value
    @lru_cache(maxsize=12)
    def cached(args):
        # Return immutable stored snapshot; callers receive an independent copy.
        def thaw(value):
            return [thaw(v) for v in value] if isinstance(value,tuple) else value
        return function(*(thaw(a) for a in args))
    @wraps(function)
    def wrapped(*args):
        return deepcopy(cached(tuple(freeze(a) for a in args)))
    return wrapped

def espacer_comparaison(fig):
    fig.update_layout(
        title_text="", transition=dict(duration=0),
        legend=dict(orientation="h",x=0,y=1.02,yanchor="bottom",
                    font=dict(size=14),tracegroupgap=5),
        margin=dict(t=52,b=45,l=85,r=15))
    return fig


_population_source = population_affichee

@lru_cache(maxsize=24)
def _population_territoriale(annee,dept,classe,unite,mode,profiles):
    # Une seule sélection / équilibrage pour les quatre analyses territoriales.
    return _population_source(annee,"all",list(dept),classe,unite,
        "dept_conso","qualite_isolation","classe_dpe",mode,profiles)

_population_autres = memoiser_affichage(_population_source)

def population_affichee(annee,source,dept,classe,unite,vue,facteur,angle,mode,profiles):
    if vue.startswith("dept_"):
        key_profiles=tuple(tuple(p or []) for p in profiles)
        base,q,note,scenario,depts=_population_territoriale(
            annee,tuple(sorted(set(dept or []))),classe,unite,mode,key_profiles)
        # base n'est que consultée par les appelants ; q reste une copie indépendante.
        return base,q.copy(),note,scenario,list(dept or [])
    return _population_autres(annee,"all",dept,classe,unite,vue,facteur,angle,mode,profiles)


@app.callback(Output("cards","children"),Output("map","figure"),Output("lecture","children"),Output("effectifs","children"),
    Input("annee","value"),Input("source","value"),Input("dept","value"),Input("classe","value"),Input("unite","value"),Input("transition","value"),Input("stat","value"),State("angle","value"),Input("mode-territoire","value"),
    *[Input(i,"value") for i in PROFILE_IDS])
@memoiser_affichage
def actualiser(annee,source,dept,classe,unite,transition,stat,angle,mode,*profiles):
    angle="classe_dpe"
    facteur="qualite_isolation"
    vue="dept_conso" if dept else "ecart"  # La comparaison principale reste visible pendant l’exploration.
    base,q,info_equilibre,scenario_angle,depts=population_affichee(annee,source,dept,classe,unite,vue,facteur,angle,mode,profiles)
    k=compute_kpis(q,transition)
    lab,dec=UNITES[unite][:2]
    if unite=="kwh": lab="kWh/logement/an"
    if k:
        sens="Enedis supérieur au DPE" if k['ecart']>0 else "Enedis inférieur au DPE" if k['ecart']<0 else "Écart moyen nul"
        cards=[carte_kpi("1 · Quel décalage moyen entre Enedis et DPE ?",fs(k['ecart'],dec)+" "+lab,sens+" en moyenne.", "#B66516" if k["ecart"]>0 else "#246BB0" if k["ecart"]<0 else "#64748B"),
            carte_kpi("2 · Les écarts varient-ils selon les adresses ?",fmt(k['ecart_type'],dec)+" "+lab,"Écart-type : plus il est élevé, plus les écarts varient.")]

    else:
        cards=[carte_kpi(t,"—","Aucune donnée admissible : vérifier origine, année, unité et mode d’équilibrage.") for t in ["1 · Écart moyen","2 · Écart-type"]]
    carte=fig_carte(q if depts else base,stat,depts,"click",unite)
    for trace in carte.data:
        if trace.type=="choropleth":
            trace.customdata=[NOMS_DEPT.get(str(code),str(code)) for code in trace.locations]
            trace.hovertemplate="%{customdata}<extra></extra>"
        elif trace.type=="scattergeo":trace.hoverinfo="skip"
    carte.update_layout(uirevision="carte-stable")
    if stat == "ecart_type":
        carte.update_layout(coloraxis_colorscale=PALETTE_DISPERSION, coloraxis_cmin=0)
        carte.layout.coloraxis.colorbar.title.text = "Écart-type<br>" + lab + "<br>Foncé = plus dispersé"

    if vue.startswith("dept_"):
        fig,note=figure_departements(q,depts,vue,facteur,unite)
        note=info_equilibre+note
    elif vue=="ecart":
        fig=fig_ecart(q,unite) if angle=="classe_dpe" else figure_angle(q,angle,unite,False)
        note="Deux moyennes calculées sur les mêmes adresses. Leur différence correspond à l’écart moyen de la classe. Survolez les barres pour les valeurs et les effectifs."
    elif vue=="histogramme":
        fig=fig_histogramme(eligibles_dispersion(q),unite)
        note="Même population que le KPI 2 : au moins deux adresses distinctes dans le groupe affiché. La dispersion n’explique pas les causes."
    elif vue=="scatter":
        fig=fig_scatter(q,unite) if angle=="classe_dpe" else figure_angle(q,angle,unite,True)
        note="Proche = ±10 % du DPE, seuil pédagogique et non norme officielle. Part calculée sur les comparaisons valides (DPE > 0, Enedis ≥ 0). Les trois catégories totalisent 100 % avant arrondi."
    elif vue=="caracteristiques":
        fig=fig_facteur(q,facteur,unite)
        note="Consommations médianes Enedis et DPE par catégorie. Comparaison descriptive : les autres caractéristiques peuvent différer."
    elif vue=="dispersion_caracteristiques":
        fig=fig_dispersion_facteur(q,facteur,unite)
        note="Écart-type des écarts par catégorie (au moins 2 adresses). Même population que le KPI 2 et la distribution ; une catégorie de moins de 2 adresses reste sans barre. Effectifs au survol. Aucune cause démontrée."
    elif vue=="usage":
        scenario=q.loc[q.donnee_simulee].copy()
        g=differences(scenario,colonnes=[u[0] for u in USAGES],minimum=MIN_STRATE,moyenne=True)
        g=g.loc[(g.passage==transition)&g.stratifie]
        if g.empty:
            fig=fig_vide("Usages DPE · données simulées comparables insuffisants")
        else:
            r=g.iloc[0]
            fig=go.Figure(go.Bar(x=[u[1] for u in USAGES],y=[r[u[0]] for u in USAGES],marker_color=COULEUR_DPE))
            fig=habiller(fig,"Différence "+transition+" par usage DPE · données simulées")
            fig.update_yaxes(title=lab,rangemode="tozero")
            fig.add_hline(y=0,line_color=COULEUR_TEXTE)
        note="DPE uniquement, données simulées : différences de MOYENNES par usage pour assurer l’additivité. Le KPI 3 utilise des médianes ; les valeurs ne sont donc pas identiques. Enedis ne détaille pas ces usages."
    else:
        g=gains_classes(q); g=g.loc[(g.passage==transition)&g.stratifie]
        fig=go.Figure()
        if g.empty:
            fig=fig_vide("Effectifs comparables insuffisants")
        else:
            r=g.iloc[0]
            for nom,col,pct,couleur,motif in [("Enedis","enedis_kwh","enedis_pct",COULEUR_ENEDIS,""),("DPE","dpe_kwh","dpe_pct",COULEUR_DPE,"/")]:
                fig.add_trace(go.Bar(x=[nom],y=[r[col]],name=nom,marker_color=couleur,marker_pattern_shape=motif,text=[fs(r[col],dec)],textposition="auto",customdata=[[r[pct]]],hovertemplate="%{x} : %{y:.1f}<br>%{customdata[0]:.1f} %<extra></extra>"))
            fig=habiller(fig,"Différence "+transition+" · mêmes profils comparables")
            fig.update_yaxes(title=lab,rangemode="tozero");fig.add_hline(y=0,line_color=COULEUR_TEXTE)
        note="Médiane de départ − médiane d’arrivée, par profils comparables, puis pondération commune. ≥ 10 adresses par classe/profil. Ce n’est pas une économie de rénovation démontrée."
    if angle == "usages_appareils":
        note="Ventilation simulée : cinq usages comparés au DPE à gauche ; appareils par type de logement à droite. Aucun détail Enedis mesuré. Les appareils ne sont pas inclus dans le DPE."
    if angle == "type_logement":
        note += " Maisons et appartements équilibrés dans les données simulées ; surfaces et profils différents, aucune causalité démontrée."
    if scenario_angle:
        note="Données simulées uniquement. "+note
        if angle=="appareils_groupe": note+=" Les appareils font partie du total simulé : association en partie construite."
    if classe!="all" and vue=="gain": note+=" Choisissez Toutes les classes pour comparer les deux classes."
    if k and k["adresses"]<10: note+=" Petit échantillon : lecture illustrative uniquement."
    for f in [carte,fig]: f.update_layout(height=None,width=None,autosize=True)
    fig.update_layout(title_text=("Usages électriques" if angle=="usages_appareils" else "Consommation moyenne") if not q.empty else "Aucune donnée admissible",margin=dict(t=55,b=35,l=40,r=10),font=dict(size=10),legend=dict(font=dict(size=16)))
    if q.empty:
        raison = ("Aucune comparaison réelle validée dans le dataset." if source=="valide" else
                  "Intensités originales indisponibles : surface proxy non concordante." if unite=="m2" and source=="reel" else
                  "Aucune observation avec ces filtres.")
        fig = fig_vide(raison)
        fig.layout.annotations[0].text = raison
        note = raison
    else:
        note = ("" if q.donnee_simulee.all() else
                "Sources originales à vérifier : électricité finale DPE et historique non validés. ") + note
    if angle == "usages_appareils":
        fig.update_layout(margin=dict(t=60,b=40,l=115,r=15),legend=dict(y=1.02,font=dict(size=16)))
    n_sim=int(q.donnee_simulee.sum())
    effectifs=f"{len(q):,} observations · {q.id_adresse_panel.nunique():,} adresses · {len(q)-n_sim:,} originales / {n_sim:,} simulées · "+(", ".join(NOMS_DEPT.get(d,d) for d in depts) if depts else "Ensemble disponible · non représentatif de la France")+" · Filtres profils : "+str(sum(bool(v) for v in profiles))
    espacer_comparaison(fig)
    return cards,carte,"",effectifs


# Chaque rubrique ne présente que deux ou trois boutons de détail.
RUBRIQUES={
    "comparaison":[("ecart","Consommations par classe"),("scatter","Proportions des adresses")],
    "variabilite":[("histogramme","Distribution"),("dispersion_caracteristiques","Par caractéristique")],
    "territoires":[("dept_conso","Consommations"),("dept_ecart","Écart moyen"),("dept_dispersion","Dispersion"),("dept_composition","Profils")],
}
@app.callback(Output("vue","options"),Output("vue","value"),Input("rubrique","value"))
def changer_rubrique(rubrique):
    vues=RUBRIQUES.get(rubrique,RUBRIQUES["comparaison"])
    return [{"label":label,"value":v} for v,label in vues],vues[0][0]

@app.callback(Output("facteur-wrap","style"),Input("vue","value"))
def afficher_facteur(vue):
    return {"display":"block" if vue=="dept_composition" else "none","marginBottom":"6px"}


@app.callback(Output("profils-modal","style"),Input("ouvrir-profils","n_clicks"),Input("fermer-profils","n_clicks"),prevent_initial_call=True)
def ouvrir_filtres(a,b):
    from dash import ctx
    return {"display":"flex" if ctx.triggered_id=="ouvrir-profils" else "none"}

@app.callback(*[Output(i,"value") for i in PROFILE_IDS],Input("effacer-profils","n_clicks"),prevent_initial_call=True)
def effacer_filtres(n): return [[] for _ in PROFILE_IDS]

@app.callback(Output("angle-wrap","style"),Output("territoire-wrap","style"),Input("vue","value"))
def controles_vue(vue):
    return {"display":"block"},{"display":"block"}


@app.callback(Output("annee","value"),Output("source","value"),Output("dept","value",allow_duplicate=True),
    Output("classe","value"),Output("mode-territoire","value"),
    *[Output(i,"value",allow_duplicate=True) for i in PROFILE_IDS],
    Input("exemple-original","n_clicks"),prevent_initial_call=True)
def exemple_original(n):
    # Exemple de filtres sur les données disponibles du fichier.
    return ("2024","all",["83","92"],"E","brut",
        ["0-30"],[],[],["insuffisante"],["Électricité"],[],["appartement"],[])


# Historique des filtres : instantanés, restauration et branche redo invalidée.
HISTORY_IDS=["annee","source","dept","classe","unite","transition","stat","mode-territoire"]+PROFILE_IDS
@app.callback(Output("historique","data"),Output("undo","disabled"),Output("redo","disabled"),Output("history-status","children"),
    *[Output(i,"value",allow_duplicate=True) for i in HISTORY_IDS],
    *[Input(i,"value") for i in HISTORY_IDS],Input("undo","n_clicks"),Input("redo","n_clicks"),State("historique","data"),prevent_initial_call=True)
def historique(*args):
    values=list(args[:len(HISTORY_IDS)]);h=args[-1] or {"past":[],"present":None,"future":[]}
    h={k:list(h[k]) if k!="present" else h[k] for k in h}
    restore=[no_update]*len(HISTORY_IDS)
    if ctx.triggered_id=="undo" and h["past"]:
        h["future"].insert(0,h["present"]);h["present"]=h["past"].pop();restore=h["present"]
    elif ctx.triggered_id=="redo" and h["future"]:
        h["past"].append(h["present"]);h["present"]=h["future"].pop(0);restore=h["present"]
    elif values!=h["present"]:
        if h["present"] is not None:h["past"].append(h["present"])
        h["past"]=h["past"][-30:];h["present"]=values;h["future"]=[]
    return (h,not bool(h["past"]),not bool(h["future"]),str(len(h["past"]))+" étape(s) annulable(s)",*restore)

DETAIL_INPUTS=[State(i,"value") for i in ["annee","source","dept","classe","unite","vue","facteur","angle","mode-territoire"]+PROFILE_IDS]
def donnees_selection(args):
    base,q,info,scenario,depts=population_affichee(*args[:9],args[9:])
    columns=["id_adresse_panel","annee","adresse","commune","code_departement","classe_dpe","surface_m2","type_logement","energie_chauffage","qualite_isolation","conso_dpe_unifiee_kwh","conso_enedis_unifiee_kwh","ecart_kwh","source_dpe","source_enedis","donnee_simulee","statut_comparabilite","comparaison_reelle_validee","statut_surface_analyse"]
    columns += COLONNES_DETAIL + ["nb_equipements_electromenagers_scenario","origine_detail_usages","extension_scenario"]
    result=q[[c for c in columns if c in q]].copy()
    result["unite_consommations_affichees"]="kWh/m²/an" if args[4]=="m2" else "kWh/logement/an"
    return result

@app.callback(Output("export-csv","data"),Input("exporter","n_clicks"),*DETAIL_INPUTS,prevent_initial_call=True)
def exporter(n,*args):
    q=donnees_selection(args)
    # Les données source restent intactes ; l’unité des valeurs affichées est explicite.
    if args[4]=="m2":q=q.rename(columns={c:c.replace("_kwh","_kwh_m2") for c in ["conso_dpe_unifiee_kwh","conso_enedis_unifiee_kwh","ecart_kwh"] + COLONNES_DETAIL})
    return dcc.send_data_frame(q.to_csv,"selection_dpe_enedis_"+str(args[0])+".csv",index=False,sep=";",encoding="utf-8-sig")

@app.callback(Output("details-modal","style"),Output("details-table","data"),Output("details-table","columns"),Output("details-resume","children"),
    Input("ouvrir-details","n_clicks"),Input("fermer-details","n_clicks"),*DETAIL_INPUTS,prevent_initial_call=True)
def details(a,b,*args):
    if ctx.triggered_id=="fermer-details":return {"display":"none"},no_update,no_update,no_update
    q=donnees_selection(args)
    cols=[c for c in ["annee","code_departement","adresse","classe_dpe","conso_dpe_unifiee_kwh","conso_enedis_unifiee_kwh","ecart_kwh","surface_m2","source_dpe","source_enedis","donnee_simulee","statut_comparabilite","comparaison_reelle_validee","statut_surface_analyse"] if c in q]
    table=q[cols].copy()
    for c in table.select_dtypes(include="number"):table[c]=table[c].round(2)
    records=json.loads(table.to_json(orient="records"))
    mean=q.ecart_kwh.mean()
    unit="kWh/m²/an" if args[4]=="m2" else "kWh/logement/an"
    summary=f"{len(q)} observations. Écart moyen Enedis − DPE : {fmt(mean,1)} {unit}. Un signe positif indique Enedis supérieur au DPE."
    return {"display":"flex"},records,[{"name":c.replace("_"," "),"id":c} for c in cols],summary

@app.callback(Output("territory-cards","children"),Output("territory-cards","style"),
    Output("factor-hover","style"),Output("vue","style"),
    Input("rubrique","value"),State("vue","value"),State("facteur","value"),
    Input("annee","value"),Input("source","value"),Input("dept","value"),Input("classe","value"),Input("unite","value"),Input("mode-territoire","value"),
    *[Input(i,"value") for i in PROFILE_IDS])
def navigation_survol(rubrique,vue,facteur,annee,source,dept,classe,unite,mode,*profiles):
    territory=bool(dept)
    if not vue.startswith("dept_"):vue="dept_conso"
    cards=[]
    if territory:
        _,q,_,_,_=population_affichee(annee,source,dept,classe,unite,"dept_conso",facteur,"classe_dpe",mode,profiles)
        unit="kWh/m²/an" if unite=="m2" else "kWh/logement/an"
        valid=1<=len(dept or [])<=5 and not q.empty
        e=fmt(q.conso_enedis_unifiee_kwh.mean(),0) if valid else "—"
        d=fmt(q.conso_dpe_unifiee_kwh.mean(),0) if valid else "—"
        values=[("dept_conso","Consommations",f"Enedis {e} · DPE {d}",unit+" · sélection réunie"),
            ("dept_ecart","Écart moyen",fs(q.ecart_kwh.mean(),0) if valid else "—",unit+" · sélection réunie"),
            ("dept_dispersion","Dispersion",fmt(q.ecart_kwh.std(),0) if valid and q.id_adresse_panel.nunique()>=2 else "—",unit+" · sélection réunie"),
            ("dept_composition","Profils",str(q.id_adresse_panel.nunique())+" adresses" if valid else "—","Adresses de la sélection")]
        for key,label,value,note in values:
            cards.append(html.Button([html.Strong(label),html.Span(value,className="hover-value"),html.Small(note)],
                className="hover-card"+(" active" if vue==key else ""),**{"data-view":key,"aria-pressed":str(vue==key).lower()}))
    return (cards,{"display":"grid" if territory else "none"},
        {"display":"block"},
        {"display":"none" if territory else "flex","marginTop":"8px"})

@app.callback(Output("territory-cache","data"),Output("territory-band","style"),
    Input("annee","value"),Input("source","value"),Input("dept","value"),Input("classe","value"),Input("unite","value"),
    Input("mode-territoire","value"),*[Input(i,"value") for i in PROFILE_IDS])
@memoiser_affichage
def preparer_territoires(annee,source,dept,classe,unite,mode,*profiles):
    result={}
    signature=[str(annee),source,list(dept or []),classe,unite,mode,list(profiles)]
    result["_selection"]=signature
    if not dept:return result,{"display":"none"}
    _,q,info,_,_=population_affichee(annee,source,dept,classe,unite,
        "dept_conso","qualite_isolation","classe_dpe",mode,profiles)
    agregats=q.groupby("dept_code",observed=True).agg(
        n=("id_adresse_panel","nunique"),dpe=("conso_dpe_unifiee_kwh","mean"),
        enedis=("conso_enedis_unifiee_kwh","mean"),ecart=("ecart_kwh","mean"),
        dispersion=("ecart_kwh","std"))
    for vue in ["dept_conso","dept_ecart","dept_dispersion","dept_composition"]:
        for facteur in (list(FACTEURS) if vue=="dept_composition" else ["qualite_isolation"]):
            fig,note=figure_departements(q,list(dept),vue,facteur,unite,agregats=agregats)
            title=fig.layout.title.text or ""
            fig.update_layout(title_text="",height=None,width=None,autosize=True,
                margin=dict(t=65,b=90,l=100,r=30),font=dict(size=14),transition=dict(duration=0),
                legend=dict(orientation="h",x=0,y=-.25,xanchor="left",yanchor="top",font=dict(size=12)))
            fig.update_xaxes(automargin=True);fig.update_yaxes(automargin=True)
            result[vue+":"+facteur]={"figure":json.loads(fig.to_json()),"note":title+". "+info+note}
    return result,{"display":"flex"}

app.clientside_callback(
    """function(cache,vue,facteur,annee,source,depts,classe,unite,mode,...profiles){
        const signature=[String(annee),source,depts||[],classe,unite,mode,profiles];
        if(!cache||JSON.stringify(cache._selection)!==JSON.stringify(signature))return ["Mise à jour de la sélection…","Mise à jour en cours"];
        vue=vue&&vue.startsWith('dept_')?vue:'dept_conso';
        document.querySelectorAll('[data-view]').forEach(b=>{
            const active=b.dataset.view===vue;
            b.classList.toggle('active',active);
            b.setAttribute('aria-pressed',String(active));
        });
        const key=vue+':'+(vue==='dept_composition'?facteur:'qualite_isolation');
        const item=cache&&cache[key];
        document.querySelectorAll('[data-profile]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.profile===facteur)));
        if(!item)return ['Sélectionnez des départements ou attendez le chargement',''];
        const figure=JSON.parse(JSON.stringify(item.figure));
        const graph={namespace:'dash_core_components',type:'Graph',props:{
            id:'territory-graph',figure:figure,responsive:true,
            config:{displayModeBar:false},className:'plot',style:{flex:1,minHeight:0}}};
        return [{namespace:'dash_html_components',type:'Div',props:{
            key:JSON.stringify(signature)+key,
            style:{display:'flex',flexDirection:'column',flex:1,minHeight:0},
            children:graph}},item.note];
    }""",
    Output("territory-graph-host","children"),Output("territory-note","children"),
    Input("territory-cache","data"),Input("vue","value"),Input("facteur","value"),
    Input("annee","value"),Input("source","value"),Input("dept","value"),Input("classe","value"),Input("unite","value"),Input("mode-territoire","value"),*[Input(i,"value") for i in PROFILE_IDS])

app.clientside_callback(
    """function(open, depts) {
        const trigger=dash_clientside.callback_context.triggered_id;
        if(!depts||!depts.length){
            window.territoryPinned=false;
            if(open)dash_clientside.set_props('territory-open',{data:false});
            return 'right-column';
        }
        requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));
        return (open||trigger==='dept')?'right-column territory-visible':'right-column';
    }""",
    Output("right-zone","className"),Input("territory-open","data"),Input("dept","value"))

@app.callback(Output("variability-cache","data"),
    Input("annee","value"),Input("source","value"),Input("dept","value"),Input("classe","value"),Input("unite","value"),State("angle","value"),
    *[Input(i,"value") for i in PROFILE_IDS])
@memoiser_affichage
def preparer_variabilite(annee,source,dept,classe,unite,angle,*profiles):
    angle="classe_dpe"
    _,q,_,_,_=population_affichee(annee,source,dept,classe,unite,"ecart","qualite_isolation",angle,"brut",profiles)
    q=eligibles_dispersion(q)
    figures={key:fig_dispersion_facteur(q,key,unite) for key in TECH_FACTEURS}
    figures["distribution"]=fig_histogramme(q,unite)
    for fig in figures.values():fig.update_layout(title_text="",height=None,width=None,autosize=True,margin=dict(t=12,b=45,l=130,r=20),font=dict(size=14),transition=dict(duration=0))
    for key,fig in figures.items():
        fig.update_yaxes(automargin=True)
        fig.update_layout(title_text="")
    return {key:json.loads(fig.to_json()) for key,fig in figures.items()}

app.clientside_callback(
    """function(cache, facteur, vue){
        const keys="""+json.dumps(list(TECH_FACTEURS))+""";
        const fig=cache?(cache[vue==='distribution'?'distribution':facteur]||dash_clientside.no_update):dash_clientside.no_update;
        return [fig,...keys.map(k=>'factor-item'+(vue!=='distribution'&&k===facteur?' active':''))];
    }""",
    Output("variability-graph","figure"),*[Output("hover-"+k,"className") for k in TECH_FACTEURS],
    Input("variability-cache","data"),Input("facteur","value"),Input("variability-view","value"))


app.clientside_callback(
    """function(value){
        document.querySelectorAll('.angle-hover-button').forEach(function(b){
            b.setAttribute('aria-pressed',String(b.dataset.angle===value));
        });
        return window.dash_clientside.no_update;
    }""",
    Output("angle-caption","title"),Input("angle","value"))


@app.callback(Output("comparison-cache","data"),
    Input("annee","value"),Input("source","value"),Input("dept","value"),
    Input("classe","value"),Input("unite","value"),
    *[Input(i,"value") for i in PROFILE_IDS])
@memoiser_affichage
def preparer_comparaisons(annee,source,dept,classe,unite,*profiles):
    result={}
    for angle in ["classe_dpe","type_logement","usages_appareils","tranche_surface","occupation_groupe"]:
        _,q,_,_,_=population_affichee(annee,source,dept,classe,unite,
            "ecart","qualite_isolation",angle,"brut",profiles)
        left=fig_ecart(q,unite) if angle=="classe_dpe" else figure_angle(q,angle,unite,False)
        right=fig_scatter(q,unite) if angle=="classe_dpe" else figure_angle(q,angle,unite,True)
        for f in [left,right]:
            espacer_comparaison(f)
            f.update_layout(height=None,width=None,autosize=True)
        result[angle]=[json.loads(left.to_json()),json.loads(right.to_json())]
    return result

app.clientside_callback(
    """function(cache,angle){
        const pair=cache && cache[angle||'classe_dpe'];
        if(!pair)return [dash_clientside.no_update,dash_clientside.no_update];
        return pair.map(f=>JSON.parse(JSON.stringify(f)));
    }""",
    Output("graph","figure"),Output("proportions-graph","figure"),
    Input("comparison-cache","data"),Input("angle","value"))


app.clientside_callback(
    """function(angle,facteur,vue){
        const labels={classe_dpe:'classe DPE',type_logement:'type de logement',tranche_surface:'tranche de surface',occupation_groupe:'nombre d’occupants',usages_appareils:'usage électrique'};
        const factors="""+json.dumps(FACTEURS,ensure_ascii=False)+""";
        const label=labels[angle]||'classe DPE';
        const left=angle==='usages_appareils'?'Cinq usages : estimations DPE et consommations simulées':'Consommations moyennes Enedis et DPE par '+label;
        const right=angle==='usages_appareils'?'Consommation des appareils : comparaison maisons / appartements (données simulées)':(angle==='classe_dpe'?'Part des observations inférieures, proches (±10 %) ou supérieures au DPE — toutes classes sélectionnées':'Part des observations inférieures, proches (±10 %) ou supérieures au DPE par '+label);
        const distribution=vue==='distribution';
        return [left,right,distribution?'Nombre d’observations selon leur écart Enedis − DPE':'Écart-type des écarts selon '+(factors[facteur]||facteur)+' : plus la barre est longue, plus les écarts diffèrent.',{display:distribution?'block':'none'}];
    }""",
    Output("comparison-left-caption","children"),Output("comparison-right-caption","children"),
    Output("variability-caption","children"),Output("zero-reference","style"),
    Input("angle","value"),Input("facteur","value"),Input("variability-view","value"))

app.clientside_callback(
    """async function(n,territory,comparison,variability,angle,year,source,depts,classe,unit,mode){
        if(!n)return dash_clientside.no_update;
        if(document.querySelector('[data-dash-is-loading="true"]'))return 'Attendez la fin de la mise à jour avant l’export.';
        const win=window.open('','_blank');
        if(!win)return 'Autorisez la fenêtre d’export dans votre navigateur.';
        const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        win.document.write('<!doctype html><html lang="fr"><head><title>Rapport DPE — Enedis</title><style>body{font:14px Arial;color:#173b5c;margin:30px}h1{font-size:24px}img{width:100%}section{break-inside:avoid;break-before:page;margin:0}h2{font-size:20px;margin:0 0 12px}img{max-height:155mm;object-fit:contain}.kpis{white-space:pre-line;padding:15px;background:#eef3f9}button{padding:12px}@media print{button{display:none}}@page{size:A4 landscape;margin:12mm}</style></head><body><h1>Comparaison DPE — Enedis</h1><p id="progress">Préparation des graphiques…</p></body></html>');
        win.document.close();
        // Normalisation réservée à l'export, sans modifier les caches ou le CSV.
        const textePDF=s=>String(s??'').replace(/\\bsimul(?:é|e)(?:e)?s?\\b/gi,'').replace(/ {2,}/g,' ').trim();
        const figurePDF=value=>{
            if(typeof value==='string')return textePDF(value);
            if(Array.isArray(value))return value.map(figurePDF);
            if(value && typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,figurePDF(v)]));
            return value;
        };
        const names=""" + json.dumps(NOMS_DEPT,ensure_ascii=False) + """;
        const selectedNames=(depts||[]).map(d=>names[d]?d+' — '+names[d]:d);
        const uniteLabel=unit==='m2'?'kWh/m²/an':'kWh/logement/an';
        const angleLabels={classe_dpe:'classe DPE',type_logement:'type de logement',
            tranche_surface:'tranche de surface',occupation_groupe:'nombre d’occupants'};
        const factorLabels={qualite_isolation:'qualité de l’isolation',
            periode_construction:'période de construction',chauffage_installation:'installation de chauffage',
            type_logement:'type de logement',classe_dpe:'classe DPE',tranche_surface:'tranche de surface',
            occupation_groupe:'nombre d’occupants',energie_chauffage:'énergie de chauffage'};
        const append=(tag,text)=>{const e=win.document.createElement(tag);e.textContent=textePDF(text);win.document.body.appendChild(e);return e;};
        append('p','Année : '+year+' · Départements : '+(selectedNames.join(', ')||'ensemble disponible')+' · Classe DPE : '+(classe==='all'?'Toutes les classes':classe)+' · Unité : '+uniteLabel+' · Population : '+(mode==='equilibre'?'profils communs équilibrés':'toutes les adresses filtrées'));
        append('p','Les résultats décrivent la sélection ; ils ne démontrent pas une causalité. Le fichier comporte des valeurs générées, qui ne sont pas des mesures Enedis.');
        const k=append('div',document.getElementById('cards')?.innerText||'');k.className='kpis';
        append('p',(document.getElementById('effectifs')?.textContent||'').split(' · ').slice(0,2).join(' · '));
        const figs=[];
        const pair=comparison?.[angle||'classe_dpe'];
        if(pair){
            const usage=angle==='usages_appareils';
            figs.push([usage?'Consommations des cinq usages électriques':'Consommations moyennes Enedis et DPE par '+(angleLabels[angle]||'classe DPE'),pair[0]]);
            figs.push([usage?'Consommation des appareils : maisons et appartements':
                'Adresses avec une consommation inférieure, proche ou supérieure au DPE'+(angle==='classe_dpe'?' — ensemble sélectionné':' par '+(angleLabels[angle]||'profil')),pair[1]]);
        }
        if(variability?.distribution)figs.push(['Distribution des écarts — zéro signifie Enedis = DPE',variability.distribution]);
        if(depts?.length)Object.entries(territory||{}).filter(([key,item])=>item.figure).forEach(([key,item])=>{
            const [view,factor]=key.split(':');
            const captions={dept_conso:'Consommations moyennes Enedis et DPE par département',
                dept_ecart:'Écart moyen Enedis − DPE par département',
                dept_dispersion:'Écart-type des écarts Enedis − DPE par département',
                dept_composition:'Répartition des adresses par '+(factorLabels[factor]||factor)};
            figs.push([captions[view]||'Comparaison des départements',item.figure]);
        });
        try{
            for(const [caption,sourceFigure] of figs){
                const figure=figurePDF(sourceFigure);
                const div=document.createElement('div');div.style.cssText='position:fixed;left:-10000px;width:1100px;height:540px';document.body.appendChild(div);
                try{await Plotly.newPlot(div,JSON.parse(JSON.stringify(figure.data||[])),{...JSON.parse(JSON.stringify(figure.layout||{})),width:1100,height:540,autosize:false},{staticPlot:true});
                    const url=await Plotly.toImage(div,{format:'png',width:1100,height:540,scale:1.5});
                    const section=win.document.createElement('section');const h=win.document.createElement('h2');h.textContent=textePDF(caption).replace(/<br\\s*\\/?>(?:\\s*)/gi,' ');section.appendChild(h);
                    const img=win.document.createElement('img');img.src=url;section.appendChild(img);win.document.body.appendChild(section);await img.decode();
                }finally{Plotly.purge(div);div.remove();}
            }
            win.document.getElementById('progress').remove();
            const btn=append('button','Enregistrer en PDF / Imprimer');btn.onclick=()=>win.print();
            win.focus();win.print();return 'Rapport prêt : choisissez Enregistrer au format PDF.';
        }catch(error){append('p','Export interrompu : '+error.message);return 'Export interrompu. Réessayez après le chargement des graphiques.';}
    }""",
    Output("pdf-status","children"),Input("export-pdf","n_clicks"),
    State("territory-cache","data"),State("comparison-cache","data"),State("variability-cache","data"),
    State("angle","value"),State("annee","value"),State("source","value"),State("dept","value"),State("classe","value"),State("unite","value"),State("mode-territoire","value"),prevent_initial_call=True)

if __name__=="__main__":
    app.run(debug=False,port=8050)
