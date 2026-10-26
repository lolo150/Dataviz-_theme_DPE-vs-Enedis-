import sys,hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app as m
print('Rows loaded',len(m.D),'source counts',m.D.donnee_simulee.value_counts().to_dict())
profiles=[None]*8
for year in ['2023','2024']:
 for ds in [['83'],['83','92'],['2A','971']]:
  cache,_=m.preparer_territoires(year,'all',ds,'all','kwh','brut',*profiles)
  expected=m.D.loc[m.D.annee.eq(int(year))&m.D.dept_code.isin(ds)]
  for view in ['dept_conso','dept_ecart','dept_dispersion','dept_composition']:
   _,q,_,_,_=m.population_affichee(year,'all',ds,'all','kwh',view,'type_logement','classe_dpe','brut',profiles)
   assert set(q.id_adresse_panel)==set(expected.id_adresse_panel)
   assert np.allclose(q.ecart_kwh,q.conso_enedis_unifiee_kwh-q.conso_dpe_unifiee_kwh)
  for factor in m.FACTEURS:
   fig,note=m.figure_departements(expected,ds,'dept_composition',factor,'kwh')
   totals=np.sum([np.asarray(t.x,dtype=float) for t in fig.data],axis=0)
   assert np.allclose(totals,100)
   assert cache['dept_composition:'+factor]['figure']['data']
  print(year,ds,len(expected),'PASS')
# Verify nonuniform sample standard deviations and averages independently of figures.
from cartographie import stats_departements
q=m.D.loc[m.D.annee.eq(2024)&m.D.dept_code.isin(['83','92'])]
t=stats_departements(q,'ecart_type',2).set_index('dept_code')
for dep,g in q.groupby('dept_code'):
 diff=(g.conso_enedis_unifiee_kwh-g.conso_dpe_unifiee_kwh).to_numpy()
 assert np.isclose(t.loc[dep,'ecart_moyen'],np.mean(diff))
 assert np.isclose(t.loc[dep,'ecart_type'],np.std(diff,ddof=1))
 print('2024',dep,len(g),'Enedis',g.conso_enedis_unifiee_kwh.mean(),'DPE',g.conso_dpe_unifiee_kwh.mean(),'ecart',np.mean(diff),'std',np.std(diff,ddof=1))
for mode in ['brut','equilibre']:
 m.actualiser('2024','all',['83','92'],'all','kwh','F→E','ecart_type','classe_dpe',mode,*profiles)
 _,q,info,_,_=m.population_affichee('2024','all',['83','92'],'all','kwh','dept_conso','type_logement','classe_dpe',mode,profiles)
 print(mode,len(q),info)
client=m.app.server.test_client()
for u in ['/','/_dash-layout','/_dash-dependencies']:assert client.get(u).status_code==200
surface=pd.cut(m.D.surface_m2,[0,30,50,70,90,120,np.inf],labels=['0-30','30-50','50-70','70-90','90-120','>120'])
print('Surface band mismatch',((surface.astype(str)!=m.D.tranche_surface.astype(str))&m.D.surface_m2.notna()).sum())
print('equipment groups',m.D.equipements_groupe.value_counts().head().to_dict())
print('PASS')
