"""Carte hors ligne des 101 départements, avec cinq encarts ultramarins."""
from pathlib import Path
from html import escape
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from calculs import eligibles_dispersion
ROOT = Path(__file__).resolve().parent
GEOJSON = json.loads((ROOT/'departements.geojson').read_text())
NOMS_DEPT = {f['properties']['code']:f['properties']['nom'] for f in GEOJSON['features']}
DROM = ['971','972','973','974','976']
NOMS_ENCARTS = {'971':'Guad.', '972':'Martin.', '973':'Guyane', '974':'Réunion', '976':'Mayotte'}
GRIS, BEIGE = '#DDE4EC', '#EEDDB5'
METRIQUES = {'ecart_moyen':'Écart moyen · kWh/logement/an',
 'ecart_type':'Écart-type · kWh/logement/an','mae':'MAE · kWh/logement/an','adresses':"Nombre d'adresses"}

def stats_departements(q,stat,minimum):
    stats=q.groupby('code_departement',as_index=False).agg(
      adresses=('id_adresse_panel','nunique'),
      conso_dpe=('conso_dpe_unifiee_kwh','mean'),conso_enedis=('conso_enedis_unifiee_kwh','mean'),
      ecart_moyen=('ecart_kwh','mean'),ecart_type=('ecart_kwh','std'),mae=('ecart_absolu_kwh','mean'))
    eligible=eligibles_dispersion(q)
    dispersion=eligible.groupby('code_departement').agg(ecart_type=('ecart_kwh','std'),
        adresses_ecart_type=('id_adresse_panel','nunique'))
    stats=stats.drop(columns='ecart_type').merge(dispersion,on='code_departement',how='left')
    stats=stats.rename(columns={'code_departement':'dept_code'})
    contours=pd.DataFrame({'dept_code':list(NOMS_DEPT),'departement':list(NOMS_DEPT.values())})
    stats=contours.merge(stats,on='dept_code',how='left',validate='one_to_one')
    stats['adresses']=stats.adresses.fillna(0).astype(int)
    stats['adresses_ecart_type']=stats.adresses_ecart_type.fillna(0).astype(int)
    seuil=max(2,minimum) if stat=='ecart_type' else (1 if stat=='adresses' else minimum)
    effectif=stats.adresses_ecart_type if stat=='ecart_type' else stats.adresses
    stats['coloriable']=effectif.ge(seuil)&stats[stat].notna()
    stats['statut']=np.select([stats.adresses.eq(0),~stats.coloriable],
      ['Sans données dans la sélection','Effectif insuffisant'],default='Indicateur disponible')
    return stats


def fmt(x, dec=0):
    if pd.isna(x):
        return "Non calculable"
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def hover_departement(r):
    texte = (f"<b>{escape(r.departement)} ({r.dept_code})</b><br>"
             f"{r.statut}<br>{r.adresses} adresse(s)")
    if r.adresses:
        texte += (f"<br>DPE électrique : {fmt(r.conso_dpe)} kWh/logement/an"
                  f"<br>Enedis unifié : {fmt(r.conso_enedis)} kWh/logement/an"
                  f"<br>Écart moyen : {fmt(r.ecart_moyen)} kWh/logement/an"
                  f"<br>MAE : {fmt(r.mae)} kWh/logement/an"
                  f"<br>Écart-type : {fmt(r.ecart_type)} kWh/logement/an"
                  f"<br>Adresses éligibles à l’écart-type : {r.adresses_ecart_type}")
    return texte + "<br><i>Cliquer pour filtrer les résultats</i>"


def fig_carte(t, stat="ecart_moyen", dept_sel=None, minimum=2, unite="kwh"):
    stats = stats_departements(t, stat, minimum)
    valeurs = stats.loc[stats.coloriable, stat]
    maximum = max(1., float(valeurs.abs().max())) if len(valeurs) else 1.
    if stat == "ecart_moyen":
        vmin, vmax, palette = -maximum, maximum, [[0,"#246BB0"],[.5,"#F4F5F7"],[1,"#B66516"]]
    elif stat == "part_observee":
        vmin, vmax, palette = 0, 100, "Teal"
    else:
        vmin, vmax, palette = 0, maximum, "Viridis" if stat in ["ecart_type", "mae"] else "Blues"
    fig = go.Figure()
    # Métropole + Corse en grand ; cinq encarts sans étirer la carte du monde.
    groupes = [[c for c in NOMS_DEPT if c not in DROM]] + [[c] for c in DROM]
    for i, codes in enumerate(groupes):
        geo_id = "geo" if i == 0 else f"geo{i + 1}"
        subset = stats.loc[stats.dept_code.isin(codes)].copy()
        subset["survol"] = subset.apply(hover_departement, axis=1)
        contours = {"type": "FeatureCollection", "features": [f for f in GEOJSON["features"] if f["properties"]["code"] in codes]}
        # Trois couches disjointes : chaque département reste toujours présent.
        for nom, masque, couleur in [
            ("Sans données", subset.adresses.eq(0), GRIS),
            ("Effectif insuffisant", subset.adresses.gt(0) & ~subset.coloriable, BEIGE),
            ("Indicateur disponible", subset.coloriable, None),
        ]:
            s = subset.loc[masque]
            if s.empty:
                continue
            options = {"coloraxis": "coloraxis"} if couleur is None else {
                "colorscale": [[0, couleur], [1, couleur]], "showscale": False, "zmin": 0, "zmax": 1}
            fig.add_trace(go.Choropleth(
                geojson=contours, featureidkey="properties.code", locations=s.dept_code,
                z=s[stat] if couleur is None else [0] * len(s), geo=geo_id,
                customdata=s.survol, hovertemplate="%{customdata}<extra></extra>",
                marker_line_color="#FFFFFF", marker_line_width=.85,
                name=nom, showlegend=False, **options))
        for selection in (dept_sel or []):
            if selection not in codes:
                continue
            # Le contour souligne la sélection sans changer sa couleur statistique.
            f = next(f for f in contours["features"] if f["properties"]["code"] == selection)
            polygons = f["geometry"]["coordinates"]
            if f["geometry"]["type"] == "Polygon":
                polygons = [polygons]
            lon, lat = [], []
            for polygone in polygons:
                anneau = polygone[0]
                lon += [p[0] for p in anneau] + [None]
                lat += [p[1] for p in anneau] + [None]
            fig.add_trace(go.Scattergeo(lon=lon, lat=lat, mode="lines", geo=geo_id,
                                       line=dict(color="#152F51", width=3), hoverinfo="skip", showlegend=False))
        domaine = dict(x=[0, .96], y=[.25, 1]) if i == 0 else dict(x=[(i-1)*.2+.018, i*.2-.018], y=[.025, .19])
        fig.update_layout(**{geo_id: dict(domain=domaine, visible=False, fitbounds="locations",
                projection=dict(type="mercator"), showland=False, showcoastlines=False,
                showcountries=False, showocean=False, showlakes=False, bgcolor="rgba(0,0,0,0)")})
        if i:
            fig.add_annotation(x=(i-.5)*.2, y=.213, xref="paper", yref="paper",
                               text=f"{NOMS_ENCARTS[codes[0]]}<br>{codes[0]}", showarrow=False,
                               font=dict(size=9, color="#53657A"), xanchor="center")
    titre_couleur = METRIQUES[stat].replace(" · ", "<br>")
    fig.update_layout(height=430, margin=dict(l=8, r=64, t=8, b=12), template="plotly_white",
        paper_bgcolor="white", font=dict(family="Arial", color="#273A50", size=12),
        coloraxis=dict(colorscale=palette, cmin=vmin, cmax=vmax,
            colorbar=dict(title=dict(text=titre_couleur, font=dict(size=10)), thickness=13,
                          len=.57, y=.67, x=.98, tickfont=dict(size=10), outlinewidth=0)),
        dragmode="pan", uirevision=f"carte-{stat}-{minimum}")
    if unite == "m2":
        for trace in fig.data:
            if trace.type == "choropleth" and trace.customdata is not None:
                trace.customdata = [str(t).replace("kWh/logement/an", "kWh/m²/an") for t in trace.customdata]
        fig.layout.coloraxis.colorbar.title.text = titre_couleur.replace("kWh/logement/an", "kWh/m²/an")
    return fig

