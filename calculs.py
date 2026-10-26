"""Calculs descriptifs communs aux graphiques et aux exports."""
import numpy as np
import pandas as pd

E = "conso_enedis_unifiee_kwh"
DPE = "conso_dpe_unifiee_kwh"
CLASSES = list("ABCDEFG")
USAGES = ["conso_dpe_chauffage_kwh", "conso_dpe_ecs_kwh", "conso_dpe_refroidissement_kwh",
          "conso_dpe_eclairage_kwh", "conso_dpe_auxiliaires_kwh"]
# On ne mélange ni les années ni les sources au sein d'un groupe comparable.
STRATES = ["annee", "nature_donnees", "zone_climatique", "tranche_surface",
           "energie_chauffage", "type_logement"]
PROFILS = ["annee", "nature_donnees", "classe_dpe", "tranche_surface",
           "energie_chauffage", "type_logement"]


def differences(q, colonnes=None, minimum=10, moyenne=False):
    """Différences à composition commune. Aucun remplacement par un total brut.

    Chaque strate reçoit le poids min(n_classe_depart, n_classe_arrivee).
    Les mêmes groupes et poids servent à Enedis, au DPE et aux usages.
    Moyenne par usage pour conserver l'additivité des cinq contributions.
    """
    colonnes = colonnes or [E, DPE]
    base = q.dropna(subset=STRATES + colonnes).copy()
    agg = {"n": ("id_adresse_panel", "nunique")}
    agg.update({c: (c, "mean" if moyenne else "median") for c in colonnes})
    med = base.groupby(STRATES + ["classe_dpe"], observed=True).agg(**agg).reset_index()
    resultats = []
    for depart, arrivee in zip("GFEDCB", "FEDCBA"):
        j = med[med.classe_dpe == depart].merge(med[med.classe_dpe == arrivee],
                                                on=STRATES, suffixes=("_depart", "_arrivee"))
        j = j.loc[(j.n_depart >= minimum) & (j.n_arrivee >= minimum)]
        r = {"passage": f"{depart}→{arrivee}", "strates": len(j),
             "n": int((j.n_depart + j.n_arrivee).sum()), "stratifie": bool(len(j)),
             "statut": "comparable" if len(j) else "effectif insuffisant"}
        for c in colonnes:
            poids = np.minimum(j.n_depart, j.n_arrivee)
            a = float(np.average(j[c + "_depart"], weights=poids)) if len(j) else np.nan
            b = float(np.average(j[c + "_arrivee"], weights=poids)) if len(j) else np.nan
            r[c] = a - b
            r[c + "_pct"] = (a - b) / a * 100 if a > 0 else np.nan
        resultats.append(r)
    return pd.DataFrame(resultats)


def profils(q, minimum=10):
    """Centrage sur la médiane du profil dans la sélection, sans modèle prédictif."""
    base = q.dropna(subset=PROFILS).copy()
    base["ecart_kwh"] = base[E] - base[DPE]
    g = base.groupby(PROFILS, observed=True).agg(
        n_profil=("id_adresse_panel", "nunique"), med_profil=("ecart_kwh", "median"))
    base = base.merge(g, on=PROFILS, how="left", validate="many_to_one")
    base["ecart_centre"] = (base.ecart_kwh - base.med_profil).where(base.n_profil.ge(minimum))
    return base


def eligibles_dispersion(q):
    """All admissible pairs; std requires >=2 distinct addresses at aggregation.

    Do not silently remove singleton DPE classes from a departmental population.
    """
    finite=np.isfinite(q[E]) & np.isfinite(q[DPE]) & np.isfinite(q.ecart_kwh)
    return q.loc[finite].copy()


def panel(q):
    """Revalider le panel après filtres, plutôt que faire confiance à un flag."""
    cle = "id_adresse_panel"
    cols = [cle, "annee", "adresse", "code_departement", "commune", "nb_logements",
            "nature_donnees", "surface_m2", E, DPE]
    base = q.loc[q.annee.isin([2023, 2024]), cols]
    if base.duplicated([cle, "annee"]).any():
        raise ValueError("Doublons adresse × année dans le panel")
    a = base[base.annee == 2023]
    b = base[base.annee == 2024]
    p = a.merge(b, on=cle, suffixes=("_2023", "_2024"), validate="one_to_one")
    meme = pd.Series(True, index=p.index)
    for c in ["adresse", "code_departement", "commune", "nb_logements", "nature_donnees"]:
        meme &= p[c + "_2023"].notna() & p[c + "_2023"].eq(p[c + "_2024"])
    p = p.loc[meme].copy()
    for c, nom in [(E, "enedis"), (DPE, "dpe")]:
        p["variation_" + nom + "_pct"] = (p[c + "_2024"] / p[c + "_2023"] - 1) * 100
    return p


def resume_facteur(q, colonne):
    if q.empty:
        return pd.DataFrame(columns=[colonne, "n", "dpe", "enedis", "ecart", "dispersion"])
    return q.groupby(colonne, observed=True, dropna=False).agg(
        n=("id_adresse_panel", "nunique"), dpe=(DPE, "median"), enedis=(E, "median"),
        ecart=("ecart_kwh", "mean"), dispersion=("ecart_kwh", "std")).reset_index()
